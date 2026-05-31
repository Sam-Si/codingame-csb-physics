import os
import json
import time
import requests
import argparse


BASE_URL = "https://www.codingame.com/services"


def scrape_leaderboard(puzzle_handle, start=0, limit_players=5, output_dir="leaderboard_battles"):
    """
    Scrape battle replays from the CodinGame leaderboard.

    Saves the raw, unmodified JSON response from the CodinGame API.
    No authentication required — all data is fetched anonymously.

    The raw API response per battle contains:
      - frames: list of frame dicts with keys (gameInformation, summary, view, keyframe, agentId, stdout)
      - gameId: int
      - refereeInput: string with seed, pod config, and map checkpoint coordinates
      - scores: list of floats
      - ranks: list of ints
      - agents: list of dicts with player info (index, codingamer, agentId, score, valid)
    """
    os.makedirs(output_dir, exist_ok=True)
    session = requests.Session()

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.codingame.com",
        "Referer": f"https://www.codingame.com/multiplayer/bot-programming/{puzzle_handle}/leaderboard"
    }
    session.headers.update(headers)

    # Fetch leaderboard (no auth needed)
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

    for idx, user_row in enumerate(target_users):
        rank = start + idx + 1
        codingamer = user_row.get("codingamer", {})
        nickname = codingamer.get("pseudo") or user_row.get("pseudo")
        agent_id = user_row.get("agentId")

        if not nickname or not agent_id:
            continue

        print(f"\n[Rank #{rank}] {nickname}")
        player_folder = os.path.join(output_dir, f"rank_{rank:03d}_{nickname}")
        os.makedirs(player_folder, exist_ok=True)

        # Fetch recent battles for this agent
        list_url = f"{BASE_URL}/gamesPlayersRanking/findLastBattlesByAgentId"
        try:
            list_resp = session.post(list_url, json=[agent_id, None])
            list_resp.raise_for_status()
            battles = list_resp.json()
        except Exception as e:
            print(f"  [-] Failed to fetch battles for {nickname}: {e}")
            continue

        print(f"  [+] Found {len(battles)} battles")

        for b_idx, battle in enumerate(battles):
            game_id = battle.get("gameId") or battle.get("id")
            if not game_id:
                continue

            file_path = os.path.join(player_folder, f"battle_{game_id}.json")
            if os.path.exists(file_path):
                print(f"    [{b_idx + 1}/{len(battles)}] Skipping {game_id} (already exists)")
                continue

            print(f"    [{b_idx + 1}/{len(battles)}] Fetching game {game_id}")
            game_url = f"{BASE_URL}/gameResult/findByGameId"

            try:
                # Anonymous access: viewer_user_id = None
                game_resp = session.post(game_url, json=[game_id, None])
                game_resp.raise_for_status()
                game_data = game_resp.json()

                # Save the raw, unmodified API response
                with open(file_path, "w", encoding="utf-8") as out_file:
                    json.dump(game_data, out_file, indent=2, ensure_ascii=False)
                print(f"    [+] Saved -> {file_path}")

                time.sleep(0.15)

            except Exception as e:
                print(f"    [-] Error fetching game {game_id}: {e}")

    print("\n" + "=" * 80)
    print(f"[+] Done. Raw battle data saved to ./{output_dir}/")


def scrape_user_battles(target_user_id, puzzle_handle="coders-strike-back", output_dir="user_battles", limit_players=None):
    """
    Scrapes all battles for a specific userId by checking their own recent battles
    and scanning recent battles of other players on the leaderboard.
    """
    os.makedirs(output_dir, exist_ok=True)
    session = requests.Session()

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.codingame.com",
        "Referer": f"https://www.codingame.com/multiplayer/bot-programming/{puzzle_handle}/leaderboard"
    }
    session.headers.update(headers)

    # 1. Fetch leaderboard to resolve user info and find target user
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

    user_folder = os.path.join(output_dir, f"user_{target_user_id}_{target_username}")
    os.makedirs(user_folder, exist_ok=True)

    # We will collect all unique gameIds we find involving the target user
    matched_games = {}  # gameId -> battle_summary_dict

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

    # 3. Now scan other players to find historical battles (different agentIds / when matched against others)
    players_to_scan = raw_users
    if limit_players is not None:
        players_to_scan = raw_users[:limit_players]

    print(f"[*] Scanning battles of {len(players_to_scan)} players on the leaderboard...")

    for idx, user_row in enumerate(players_to_scan):
        codingamer = user_row.get("codingamer", {})
        nickname = codingamer.get("pseudo") or user_row.get("pseudo")
        agent_id = user_row.get("agentId")
        uid = codingamer.get("userId")

        # Skip scanning target user again since we already queried them directly
        if uid == target_user_id:
            continue

        if not nickname or not agent_id:
            continue

        print(f"\r    [{idx + 1}/{len(players_to_scan)}] Scanning player {nickname}...", end="", flush=True)

        list_url = f"{BASE_URL}/gamesPlayersRanking/findLastBattlesByAgentId"
        try:
            list_resp = session.post(list_url, json=[agent_id, None])
            list_resp.raise_for_status()
            battles = list_resp.json()
            time.sleep(0.02)  # gentle sleep between listings
        except Exception as e:
            continue

        for b in battles:
            game_id = b.get("gameId") or b.get("id")
            if not game_id or game_id in matched_games:
                continue

            # Check if our target user is one of the players in this battle
            players = b.get("players", [])
            for p in players:
                if p.get("userId") == target_user_id:
                    matched_games[game_id] = b
                    break

    print(f"\n[*] Scan complete. Found {len(matched_games)} unique battles involving user {target_user_id} ({target_username}).")

    # 4. Now download the full details of all matched battles
    print(f"[*] Downloading battle details to {user_folder}...")
    success_count = 0
    skip_count = 0

    for b_idx, (game_id, b_summary) in enumerate(sorted(matched_games.items())):
        file_path = os.path.join(user_folder, f"battle_{game_id}.json")
        if os.path.exists(file_path):
            skip_count += 1
            continue

        print(f"    [{success_count + skip_count + 1}/{len(matched_games)}] Fetching game {game_id}...")
        game_url = f"{BASE_URL}/gameResult/findByGameId"

        try:
            # Anonymous access
            game_resp = session.post(game_url, json=[game_id, None])
            game_resp.raise_for_status()
            game_data = game_resp.json()

            with open(file_path, "w", encoding="utf-8") as out_file:
                json.dump(game_data, out_file, indent=2, ensure_ascii=False)
            success_count += 1
            time.sleep(0.15)
        except Exception as e:
            print(f"    [-] Error fetching game {game_id}: {e}")

    print("\n" + "=" * 80)
    print(f"[+] User Scraping Summary for {target_username} (ID: {target_user_id}):")
    print(f"    - Total unique matches identified: {len(matched_games)}")
    print(f"    - Already downloaded (skipped): {skip_count}")
    print(f"    - Successfully downloaded now: {success_count}")
    print(f"    - Destination: {user_folder}")
    print("=" * 80)


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
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Custom output directory (defaults: 'user_battles' or 'leaderboard_battles')")

    args = parser.parse_args()

    PUZZLE_NAME = "coders-strike-back"

    if args.mode == "user":
        out_dir = args.output_dir or "user_battles"
        scrape_user_battles(
            target_user_id=args.user_id,
            puzzle_handle=PUZZLE_NAME,
            output_dir=out_dir,
            limit_players=args.limit_players
        )
    else:
        out_dir = args.output_dir or "leaderboard_battles"
        scrape_leaderboard(
            puzzle_handle=PUZZLE_NAME,
            start=args.start_rank,
            limit_players=args.limit_leaderboard,
            output_dir=out_dir
        )