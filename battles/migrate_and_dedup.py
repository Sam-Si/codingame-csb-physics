import os
import json
import hashlib
import shutil
import sys

def migrate_and_deduplicate(directory):
    if not os.path.exists(directory):
        print(f"[-] Directory does not exist: {directory}")
        return

    print(f"\n================================================================================")
    print(f"[*] Processing directory: {directory}")
    print(f"================================================================================")

    # Dictionary to group files by game_id: game_id -> list of file paths
    game_groups = {}

    # Recursively scan for JSON files
    print("[*] Stage 1: Scanning all files...")
    for root, dirs, files in os.walk(directory):
        # We collect all file paths first before moving anything
        for file in files:
            if file.endswith(".json"):
                file_path = os.path.join(root, file)
                game_id = None
                
                # Try extracting gameId from filename 'battle_{gameId}.json'
                if file.startswith("battle_") and file.endswith(".json"):
                    try:
                        game_id = int(file[7:-5])
                    except ValueError:
                        pass
                
                # Fallback to parsing JSON if name is different
                if game_id is None:
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            game_id = data.get("gameId")
                    except Exception:
                        continue
                
                if game_id:
                    game_groups.setdefault(game_id, []).append(file_path)

    print(f"[+] Found {len(game_groups)} unique game IDs.")

    # Group by gameId: select the best file (authenticated/contains cerr) and move to root
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
                    # Quick substring search instead of parsing full JSON (extremely fast for 10k files)
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
            
        # Clean up any other duplicates in this game ID group
        for path in file_paths:
            if path != best_path:
                try:
                    os.remove(path)
                    deleted_id_duplicates += 1
                except Exception:
                    pass

    print(f"[+] Moved {moved_count} files directly to root.")
    print(f"[+] Cleaned up {deleted_id_duplicates} duplicate files by game ID.")

    # Gameplay physics-based deduplication using SHA256 hashing
    gameplay_hashes = {}
    duplicate_gameplays = 0

    all_root_files = [f for f in os.listdir(directory) if f.endswith(".json") and os.path.isfile(os.path.join(directory, f))]
    print(f"[*] Stage 2: Performing SHA256 gameplay physics-level deduplication on {len(all_root_files)} files...")

    for file in all_root_files:
        file_path = os.path.join(directory, file)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            # Create a physics identity representation of the game
            # refereeInput: Contains map checkpoints, seed, configurations
            ref_input = data.get("refereeInput", "")
            
            # frames: view positions, velocities, orientation, keyframes (physics simulation steps)
            frames_views = []
            for frame in data.get("frames", []):
                # We hash the structural layout/view representation of keyframes and simulation steps
                frames_views.append((frame.get("view", ""), frame.get("agentId", -1)))
                
            # Combine seed, map, and view states, and compute SHA256
            gameplay_str = f"{ref_input}_{str(frames_views)}"
            h = hashlib.sha256(gameplay_str.encode("utf-8")).hexdigest()
            
            gameplay_hashes.setdefault(h, []).append((file_path, data))
        except Exception as e:
            print(f"[-] Error hashing {file}: {e}")

    # Process gameplay duplicates (same simulation/seed/physics but different game IDs)
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

    print(f"[+] Deleted {duplicate_gameplays} files with duplicate gameplay simulation.")

    # Stage 3: Clean up empty subdirectories
    print("[*] Stage 3: Cleaning up empty subdirectories...")
    for root, dirs, files in os.walk(directory, topdown=False):
        for d in dirs:
            dir_path = os.path.join(root, d)
            if not os.listdir(dir_path):
                os.rmdir(dir_path)
                
    print(f"[+] Migration and deduplication successfully finished!")

if __name__ == "__main__":
    target_dirs = [
        "/Users/samsi/PycharmProjects/codingame-csb-physics/battles/leaderboard_battles",
        "/Users/samsi/csb/mad_pod_arena/physics/battles/leaderboard_battles"
    ]
    
    for directory in target_dirs:
        migrate_and_deduplicate(directory)
