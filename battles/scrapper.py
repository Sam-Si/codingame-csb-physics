import os
import json
import time
import requests
import argparse
import hashlib
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

BASE_URL = "https://www.codingame.com/services"
checksum_lock = threading.Lock()


def compute_sha256(file_path):
    """Computes the SHA256 checksum of a file."""
    h = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def is_file_accurate(file_path, check_stderr=False, expected_checksum=None):
    """
    Checks if a local battle JSON is valid, fully downloaded, and contains required properties.
    If expected_checksum is provided, it verifies the SHA256 hash matches.
    """
    try:
        if os.path.getsize(file_path) < 1000:  # empty or error response
            return False

        # 1. Verify SHA256 if expected
        if expected_checksum:
            current_hash = compute_sha256(file_path)
            if current_hash != expected_checksum:
                return False

        # 2. Verify JSON parseability
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return False

        if "gameId" not in data or "frames" not in data:
            return False

        frames = data.get("frames", [])
        if not isinstance(frames, list) or len(frames) == 0:
            return False

        if check_stderr:
            has_stderr = any("stderr" in frame for frame in frames)
            if not has_stderr:
                return False

        return True
    except Exception:
        return False


def get_checksum_map(directory):
    """Loads the local checksum registry file."""
    checksum_file = os.path.join(directory, ".checksums.json")
    if os.path.exists(checksum_file):
        try:
            with open(checksum_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_checksum_threadsafe(directory, game_id, file_path, checksums):
    """Computes the SHA256 checksum and adds it to the thread-safe checksum dictionary."""
    checksum = compute_sha256(file_path)
    if checksum:
        with checksum_lock:
            checksums[str(game_id)] = checksum


def migrate_and_deduplicate(directory):
    """
    Recursively scans the directory, moves all battle JSONs to the root of the directory,
    removes any empty folders, and deduplicates in two ways:
    1. By game ID: Keep the best version (authenticated with bot cerr/stderr or larger).
    2. By gameplay SHA256 hash: Group identical gameplay (seed, map, checkpoints, moves)
       under different game IDs and retain only the best single file.
    Also updates the local checksum database to keep hashes in sync.
    """
    if not os.path.exists(directory):
        print(f"[-] Directory does not exist for deduplication: {directory}")
        return

    print(f"\n" + "=" * 80)
    print(f"[*] Running automatic deduplication on: {directory}")
    print("=" * 80)

    # Dictionary to group files by game_id: game_id -> list of file paths
    game_groups = {}
    checksum_file = os.path.join(directory, ".checksums.json")

    # Recursively scan for JSON files
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith(".json") and not file.startswith("."):
                file_path = os.path.join(root, file)
                game_id = None
                
                # Extract gameId from filename 'battle_{gameId}.json'
                if file.startswith("battle_") and file.endswith(".json"):
                    try:
                        game_id = int(file[7:-5])
                    except ValueError:
                        pass
                
                # Fallback to parsing JSON if named differently
                if game_id is None:
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            game_id = data.get("gameId")
                    except Exception:
                        continue
                
                if game_id:
                    game_groups.setdefault(game_id, []).append(file_path)

    deleted_id_duplicates = 0
    moved_count = 0

    for game_id, file_paths in game_groups.items():
        target_path = os.path.join(directory, f"battle_{game_id}.json")
        
        best_path = None
        best_has_stderr = False
        best_size = -1
        
        for path in file_paths:
            has_stderr = False
            size = os.path.getsize(path)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content_head = f.read(8192)
                    if '"stderr"' in content_head or '"stdout"' in content_head:
                        has_stderr = True
            except Exception:
                pass
                
            if best_path is None:
                best_path = path
                best_has_stderr = has_stderr
                best_size = size
            else:
                if has_stderr and not best_has_stderr:
                    best_path = path
                    best_has_stderr = has_stderr
                    best_size = size
                elif has_stderr == best_has_stderr:
                    if size > best_size:
                        best_path = path
                        best_size = size
                        
        # Move the best file to root
        if best_path != target_path:
            shutil.move(best_path, target_path)
            moved_count += 1
            
        # Clean up other duplicates in this game ID group
        for path in file_paths:
            if path != best_path:
                try:
                    os.remove(path)
                    deleted_id_duplicates += 1
                except Exception:
                    pass

    if moved_count > 0 or deleted_id_duplicates > 0:
        print(f"[+] Moved {moved_count} files directly to root.")
        print(f"[+] Cleaned up {deleted_id_duplicates} duplicate files by game ID.")

    # Gameplay physics-based deduplication using SHA256 hashing
    gameplay_hashes = {}
    duplicate_gameplays = 0

    all_root_files = [f for f in os.listdir(directory) if f.endswith(".json") and os.path.isfile(os.path.join(directory, f))]

    for file in all_root_files:
        file_path = os.path.join(directory, file)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            ref_input = data.get("refereeInput", "")
            
            frames_views = []
            for frame in data.get("frames", []):
                frames_views.append((frame.get("view", ""), frame.get("agentId", -1)))
                
            gameplay_str = f"{ref_input}_{str(frames_views)}"
            h = hashlib.sha256(gameplay_str.encode("utf-8")).hexdigest()
            
            gameplay_hashes.setdefault(h, []).append((file_path, data))
        except Exception as e:
            pass

    for h, group in gameplay_hashes.items():
        if len(group) > 1:
            best_item = None
            best_has_stderr = False
            best_size = -1
            best_game_id = float("inf")
            
            for path, data in group:
                size = os.path.getsize(path)
                has_stderr = any("stderr" in frame for frame in data.get("frames", []))
                game_id = data.get("gameId", float("inf"))
                
                if best_item is None:
                    best_item = (path, data)
                    best_has_stderr = has_stderr
                    best_size = size
                    best_game_id = game_id
                else:
                    if has_stderr and not best_has_stderr:
                        best_item = (path, data)
                        best_has_stderr = has_stderr
                        best_size = size
                        best_game_id = game_id
                    elif has_stderr == best_has_stderr:
                        if size > best_size:
                            best_item = (path, data)
                            best_size = size
                            best_game_id = game_id
                        elif size == best_size:
                            if game_id < best_game_id:
                                best_item = (path, data)
                                best_game_id = game_id
                                
            best_path = best_item[0]
            for path, data in group:
                if path != best_path:
                    try:
                        os.remove(path)
                        duplicate_gameplays += 1
                    except Exception:
                        pass

    if duplicate_gameplays > 0:
        print(f"[+] Deleted {duplicate_gameplays} files with duplicate gameplay simulation.")

    # Clean up empty subdirectories
    empty_dirs_removed = 0
    for root, dirs, files in os.walk(directory, topdown=False):
        for d in dirs:
            dir_path = os.path.join(root, d)
            if not os.listdir(dir_path):
                try:
                    os.rmdir(dir_path)
                    empty_dirs_removed += 1
                except Exception:
                    pass
                
    if empty_dirs_removed > 0:
        print(f"[+] Removed {empty_dirs_removed} empty subdirectories.")

    # Regenerate local checksum database for remaining verified files
    print("[*] Re-indexing SHA256 checksum registry...")
    final_files = [f for f in os.listdir(directory) if f.endswith(".json") and os.path.isfile(os.path.join(directory, f))]
    new_checksums = {}
    for f in final_files:
        path = os.path.join(directory, f)
        # Extract gameId
        try:
            game_id = int(f[7:-5])
            checksum = compute_sha256(path)
            if checksum:
                new_checksums[str(game_id)] = checksum
        except Exception:
            pass
            
    try:
        with open(checksum_file, "w", encoding="utf-8") as f:
            json.dump(new_checksums, f, indent=2)
        print(f"[+] Re-indexed {len(new_checksums)} items in checksum database.")
    except Exception as e:
        print(f"[-] Failed to save checksum registry: {e}")

    print(f"[+] Deduplication finished successfully!")


def download_all_parallel(game_ids, output_dir, session, headers, checksums, viewer_user_id=None):
    """
    Manages sequential downloads with progress tracking, atomic temp-writes,
    and automatic 403 rate-limit backoff handling (1 worker queue).
    """
    if not game_ids:
        print("[*] No new or unverified games to download.")
        return []

    print(f"[*] Starting sequential download of {len(game_ids)} games (1 worker queue)...")
    success_count = 0
    failed_games = []
    
    # 403 rate-limit backoff tracker (starts at 10.0s, doubles on consecutive 403s)
    current_backoff = 10.0
    
    idx = 0
    retry_count = 0
    last_game_id = None
    
    while idx < len(game_ids):
        game_id = game_ids[idx]
        
        # Reset retry counter if we moved to a new game ID
        if game_id != last_game_id:
            retry_count = 0
            last_game_id = game_id
            
        file_path = os.path.join(output_dir, f"battle_{game_id}.json")
        temp_path = f"{file_path}.tmp"
        game_url = f"{BASE_URL}/gameResult/findByGameId"
        
        print(f"    [*] [{success_count + len(failed_games) + 1}/{len(game_ids)}] Fetching game {game_id}...")
        
        try:
            # Send findByGameId request
            resp = session.post(game_url, json=[game_id, viewer_user_id], headers=headers)
            
            # 1. Handle HTTP 403 Forbidden Rate-Limits
            if resp.status_code == 403:
                print(f"    [!] Received HTTP 403 Forbidden (Rate Limit). Pausing download for {current_backoff} seconds...")
                time.sleep(current_backoff)
                current_backoff = min(current_backoff * 2, 120.0) # Cap at 120s
                continue # Retry this same game ID
                
            resp.raise_for_status()
            game_data = resp.json()

            # 2. Write atomically to temp file
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(game_data, f, indent=2, ensure_ascii=False)

            # 3. Validate integrity before replacing the final file
            if is_file_accurate(temp_path, check_stderr=False):
                os.replace(temp_path, file_path)
                save_checksum_threadsafe(output_dir, game_id, file_path, checksums)
                success_count += 1
                print(f"    [+] Successfully downloaded game {game_id}")
                
                # Reset rate-limit backoff on successful download
                current_backoff = 10.0
                idx += 1 # Advance to the next game ID
                
                # Polite short pause between consecutive successful calls
                time.sleep(0.2)
            else:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
                
                retry_count += 1
                if retry_count < 3:
                    print(f"    [-] Corrupt download for game {game_id} (attempt {retry_count}/3): JSON verification failed. Retrying...")
                    time.sleep(1.0)
                else:
                    print(f"    [-] Game {game_id} failed verification 3 times (likely deleted or permanently unavailable). Skipping...")
                    failed_games.append(game_id)
                    idx += 1
                
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                print(f"    [!] HTTPError 403 Forbidden (Rate Limit). Pausing download for {current_backoff} seconds...")
                time.sleep(current_backoff)
                current_backoff = min(current_backoff * 2, 120.0)
                continue # Retry
            else:
                print(f"    [-] HTTP error downloading game {game_id}: {e}")
                failed_games.append(game_id)
                idx += 1
        except Exception as e:
            print(f"    [-] Exception downloading game {game_id}: {e}")
            failed_games.append(game_id)
            idx += 1

    print(f"\n[*] Download run complete: {success_count} succeeded, {len(failed_games)} failed.")
    return failed_games



def setup_robust_session(cookie=None):
    """
    Sets up a requests Session with HTTP adapter, pooling, and robust Retry handlers.
    """
    session = requests.Session()
    
    # Configure urllib3 advanced Retry strategy with exponential backoff
    retries = Retry(
        total=5,                         # Retry up to 5 times
        backoff_factor=0.5,              # 0.5s, 1s, 2s, 4s, 8s exponential backoff
        status_forcelist=[429, 500, 502, 503, 504], # Retry on rate-limits & server errors
        allowed_methods=["POST", "GET"]  # Retry on both POST and GET
    )
    
    # Mount adapter with connection pool sizing for concurrent threading
    adapter = HTTPAdapter(max_retries=retries, pool_connections=15, pool_maxsize=15)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.codingame.com",
    }
    
    if cookie:
        headers["cookie"] = cookie
        
    session.headers.update(headers)
    return session


def scrape_leaderboard(puzzle_handle, start=0, limit_players=5, output_dir="battles/leaderboard_battles", cookie=None):
    """
    Scrape battle replays from the CodinGame leaderboard.
    """
    os.makedirs(output_dir, exist_ok=True)
    session = setup_robust_session(cookie)

    # Fetch leaderboard
    leaderboard_url = f"{BASE_URL}/Leaderboards/getFilteredPuzzleLeaderboard"
    leaderboard_payload = [puzzle_handle, None, "global", {"active": False, "column": "", "filter": ""}]

    print(f"[*] Fetching leaderboard -> {leaderboard_url}")
    try:
        response = session.post(leaderboard_url, json=leaderboard_payload)
        response.raise_for_status()
        leaderboard_data = response.json()
    except Exception as e:
        print(f"[-] Failed to fetch leaderboard: {e}")
        return

    raw_users = leaderboard_data.get("users", [])
    target_users = raw_users[start:start + limit_players]
    print(f"[*] Processing {len(target_users)} players (ranks {start + 1} to {start + len(target_users)})")
    print("=" * 80)

    # Load local checksums registry for instant offline verification
    checksums = get_checksum_map(output_dir)
    pending_game_ids = set()

    for idx, user_row in enumerate(target_users):
        rank = start + idx + 1
        codingamer = user_row.get("codingamer", {})
        nickname = codingamer.get("pseudo") or user_row.get("pseudo")
        agent_id = user_row.get("agentId")

        if not nickname or not agent_id:
            continue

        print(f"\n[Rank #{rank}] {nickname}")

        # Fetch recent battles list
        list_url = f"{BASE_URL}/gamesPlayersRanking/findLastBattlesByAgentId"
        try:
            list_resp = session.post(list_url, json=[agent_id, None])
            list_resp.raise_for_status()
            battles = list_resp.json()
        except Exception as e:
            print(f"  [-] Failed to fetch battles list for {nickname}: {e}")
            continue

        print(f"  [+] Found {len(battles)} battles")

        for b_idx, battle in enumerate(battles):
            game_id = battle.get("gameId") or battle.get("id")
            if not game_id:
                continue

            file_path = os.path.join(output_dir, f"battle_{game_id}.json")
            
            # Fast validation with SHA256 registry check
            expected = checksums.get(str(game_id))
            if os.path.exists(file_path) and is_file_accurate(file_path, check_stderr=False, expected_checksum=expected):
                continue
                
            pending_game_ids.add(game_id)

    print("\n" + "=" * 80)
    print(f"[*] Identified {len(pending_game_ids)} new/unverified games to download.")
    print("=" * 80)

    # Run robust parallel downloader
    download_all_parallel(list(pending_game_ids), output_dir, session, session.headers, checksums)

    # Save finalized checksum database
    checksum_file = os.path.join(output_dir, ".checksums.json")
    try:
        with open(checksum_file, "w", encoding="utf-8") as f:
            json.dump(checksums, f, indent=2)
    except Exception as e:
        print(f"[-] Error writing checksum database: {e}")

    # Run auto-deduplication & cleanup
    migrate_and_deduplicate(output_dir)


def scrape_user_battles(target_user_id, puzzle_handle="coders-strike-back", output_dir="battles/leaderboard_battles", limit_players=None, cookie=None):
    """
    Scrapes all battles for a specific userId by scanning leaderboard players.
    """
    os.makedirs(output_dir, exist_ok=True)
    session = setup_robust_session(cookie)

    # 1. Fetch leaderboard
    leaderboard_url = f"{BASE_URL}/Leaderboards/getFilteredPuzzleLeaderboard"
    leaderboard_payload = [puzzle_handle, None, "global", {"active": False, "column": "", "filter": ""}]

    print(f"[*] Fetching leaderboard -> {leaderboard_url}")
    try:
        response = session.post(leaderboard_url, json=leaderboard_payload)
        response.raise_for_status()
        leaderboard_data = response.json()
    except Exception as e:
        print(f"[-] Failed to fetch leaderboard: {e}")
        return

    raw_users = leaderboard_data.get("users", [])

    # Try to find the target user in the leaderboard
    target_username = "unknown"
    target_agent_id = None
    target_rank = None

    for idx, user_row in enumerate(raw_users):
        codingamer = user_row.get("codingamer", {})
        uid = codingamer.get("userId")
        if uid == target_user_id:
            target_username = codingamer.get("pseudo") or user_row.get("pseudo") or "unknown"
            target_agent_id = user_row.get("agentId")
            target_rank = idx + 1
            print(f"[+] Found target user '{target_username}' at rank {target_rank} with current agentId {target_agent_id}")
            break

    # We will collect all unique gameIds we find involving the target user
    matched_games = {}

    # 2. First, fetch direct battles for target user's current agentId (if found)
    if target_agent_id:
        print(f"[*] Fetching direct battles for current agentId {target_agent_id}...")
        list_url = f"{BASE_URL}/gamesPlayersRanking/findLastBattlesByAgentId"
        try:
            list_resp = session.post(list_url, json=[target_agent_id, None])
            list_resp.raise_for_status()
            battles = list_resp.json()
            for b in battles:
                game_id = b.get("gameId") or b.get("id")
                if game_id:
                    matched_games[game_id] = b
            print(f"  [+] Found {len(battles)} battles directly from agentId")
        except Exception as e:
            print(f"  [-] Failed to fetch direct battles: {e}")

    # 3. Now scan other players
    players_to_scan = raw_users
    if limit_players is not None:
        players_to_scan = raw_users[:limit_players]

    print(f"[*] Scanning battles of {len(players_to_scan)} players on the leaderboard...")

    for idx, user_row in enumerate(players_to_scan):
        codingamer = user_row.get("codingamer", {})
        nickname = codingamer.get("pseudo") or user_row.get("pseudo")
        agent_id = user_row.get("agentId")
        uid = codingamer.get("userId")

        if uid == target_user_id or not nickname or not agent_id:
            continue

        print(f"\r    [{idx + 1}/{len(players_to_scan)}] Scanning player {nickname}...", end="", flush=True)

        list_url = f"{BASE_URL}/gamesPlayersRanking/findLastBattlesByAgentId"
        try:
            list_resp = session.post(list_url, json=[agent_id, None])
            list_resp.raise_for_status()
            battles = list_resp.json()
            time.sleep(0.02)
        except Exception:
            continue

        for b in battles:
            game_id = b.get("gameId") or b.get("id")
            if not game_id or game_id in matched_games:
                continue

            players = b.get("players", [])
            for p in players:
                if p.get("userId") == target_user_id:
                    matched_games[game_id] = b
                    break

    print(f"\n[*] Scan complete. Found {len(matched_games)} unique battles involving user {target_user_id} ({target_username}).")

    # Load local checksums registry for instant offline verification
    checksums = get_checksum_map(output_dir)
    pending_game_ids = set()

    for game_id in sorted(matched_games.keys()):
        file_path = os.path.join(output_dir, f"battle_{game_id}.json")
        expected = checksums.get(str(game_id))
        
        # Verify existing file integrity
        if os.path.exists(file_path) and is_file_accurate(file_path, check_stderr=False, expected_checksum=expected):
            continue
            
        pending_game_ids.add(game_id)

    print("\n" + "=" * 80)
    print(f"[*] Identified {len(pending_game_ids)} new/unverified matches to download.")
    print("=" * 80)

    # Authenticate download with the user's ID as the viewer context if cookie is supplied
    viewer_context = target_user_id if cookie else None

    # Run parallel downloads
    download_all_parallel(list(pending_game_ids), output_dir, session, session.headers, checksums, viewer_context)

    # Save checksum database
    checksum_file = os.path.join(output_dir, ".checksums.json")
    try:
        with open(checksum_file, "w", encoding="utf-8") as f:
            json.dump(checksums, f, indent=2)
    except Exception as e:
        print(f"[-] Error writing checksum database: {e}")

    # Run auto-deduplication
    migrate_and_deduplicate(output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CodinGame Battle Scraper for Coders Strike Back")
    parser.add_argument("--mode", choices=["leaderboard", "user"], default="user",
                        help="Scrape mode: 'leaderboard' (top ranks) or 'user' (all matches for a specific user) (default: user)")
    parser.add_argument("--user-id", type=int, default=984614,
                        help="CodinGame userId to scrape matches for (default: 984614 for SamSi)")
    parser.add_argument("--limit-players", type=int, default=None,
                        help="Limit the number of players scanned from the leaderboard (default: scan all)")
    parser.add_argument("--start-rank", type=int, default=0,
                        help="Start rank index for leaderboard mode (default: 0)")
    parser.add_argument("--limit-leaderboard", type=int, default=200,
                        help="Number of players to scrape in leaderboard mode (default: 200)")
    parser.add_argument("--output-dir", type=str, default="battles/leaderboard_battles",
                        help="Custom output directory (default: 'battles/leaderboard_battles')")
    parser.add_argument("--dedup", action="store_true",
                        help="Trigger standalone deduplication on the output-dir without scraping")
    parser.add_argument("--cookie", type=str, default=None,
                        help="Raw cookie string to authenticate requests and retrieve full cerr/stderr logs")

    args = parser.parse_args()

    PUZZLE_NAME = "coders-strike-back"

    if args.dedup:
        migrate_and_deduplicate(args.output_dir)
    else:
        if args.mode == "user":
            scrape_user_battles(
                target_user_id=args.user_id,
                puzzle_handle=PUZZLE_NAME,
                output_dir=args.output_dir,
                limit_players=args.limit_players,
                cookie=args.cookie
            )
        else:
            scrape_leaderboard(
                puzzle_handle=PUZZLE_NAME,
                start=args.start_rank,
                limit_players=args.limit_leaderboard,
                output_dir=args.output_dir,
                cookie=args.cookie
            )