import os
import json
import time
import requests

output_dir = "/Users/samsi/PycharmProjects/codingame-csb-physics/battles/test_session_battles"
os.makedirs(output_dir, exist_ok=True)

url = "https://www.codingame.com/services/gamesPlayersRanking/findLastBattlesByTestSessionHandle"
headers = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "content-type": "application/json;charset=UTF-8",
    "cookie": "intercom-id-h3g249np=75797091-4250-4184-b179-2135e2349b64; intercom-device-id-h3g249np=6b34348a-d9bc-44a6-aba3-2e5bbf43411a; dsq__u=4mihf6hdrcpj1; dsq__s=4mihf6hdrcpj1; rememberMe=98461425c73de6ad517a43c4056680bd821140; intercom-session-h3g249np=MUFyQm9NUGhiMUo2K1NSKzQySVNDcXhMZVlnWHpKS1BkSDJycDRVYUI1UFlzcGE1QTVhWllCVGhNSFl5dEpoU25KV0puZFFwbFRYMEhXTFN2WkxSTE9kWHlqNnJsNG1pSExqY0JERlRocE5EYTFoZnExc05Od2dObmtFenVoVGdDdnJYTUdHZEgwTEp1K3F3azYvMnBZbEVqTGlJY3lPNUh6MmFvM3pxQUNWcmk1ZXVoSG9nRVBBYzlHTnQxVTN6M1drSnRhbWM2QUtCL2txdmtKd1dxdz09LS1oWUsvM3ArYklHVGpyM3BGRVJwMTNRPT0=--ce0803c08e10926ad99b571cd7434b842311eafe; cgSession=712ef4e1-c261-4ed9-a8fa-542a4a3682a1; AWSALB=YH+Ic0OEnslkWK8A/h+vuDPNQVW9mPaaNBrW5yYye5Z4T1zuDWwIXAw6BsuDaMN86PwlwTsK6Gy7WV/51yONEWQNeqRRGRshLmjQbnEd/Azu/qZgFxO8+vVERUdA; AWSALBCORS=YH+Ic0OEnslkWK8A/h+vuDPNQVW9mPaaNBrW5yYye5Z4T1zuDWwIXAw6BsuDaMN86PwlwTsK6Gy7WV/51yONEWQNeqRRGRshLmjQbnEd/Azu/qZgFxO8+vVERUdA",
    "origin": "https://www.codingame.com",
    "referer": "https://www.codingame.com/ide/puzzle/mad-pod-racing",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
}
payload = ["4428798632da92988ae67b47269e3da4788d8f3", None]

print("[*] Fetching test session battles list...")
resp = requests.post(url, json=payload, headers=headers)
resp.raise_for_status()
battles = resp.json()
print(f"[+] Found {len(battles)} battles.")

success_count = 0
skip_count = 0

def is_file_accurate(file_path, check_stderr=False):
    """
    Checks if a local battle JSON is valid, fully downloaded, and contains the required properties.
    If check_stderr is True, it also verifies that at least one frame contains a "stderr" key with actual log content.
    """
    try:
        if os.path.getsize(file_path) < 1000:  # empty or error response
            return False
            
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


# Sequential rate-limited 403 backoff queuing loop
current_backoff = 10.0
idx = 0

while idx < len(battles):
    b = battles[idx]
    game_id = b.get("gameId") or b.get("id")
    if not game_id:
        idx += 1
        continue
        
    file_path = os.path.join(output_dir, f"battle_{game_id}.json")
    temp_path = f"{file_path}.tmp"
    
    # Skip if file already exists and is verified accurate
    if os.path.exists(file_path) and is_file_accurate(file_path, check_stderr=False):
        skip_count += 1
        idx += 1
        continue
        
    print(f"    [*] [{success_count + skip_count + 1}/{len(battles)}] Fetching game {game_id}...")
    game_url = "https://www.codingame.com/services/gameResult/findByGameId"
    
    try:
        # Use headers with credentials/cookies and viewer_user_id = 984614 to fetch the IDE battle replay data containing cerr
        game_resp = requests.post(game_url, json=[game_id, 984614], headers=headers)
        
        # Handle 403 Forbidden Rate-Limits
        if game_resp.status_code == 403:
            print(f"    [!] Received HTTP 403 Forbidden (Rate Limit). Pausing download for {current_backoff} seconds...")
            time.sleep(current_backoff)
            current_backoff = min(current_backoff * 2, 120.0)
            continue # Retry same game ID
            
        game_resp.raise_for_status()
        game_data = game_resp.json()
        
        # Atomic write to temp file
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(game_data, f, indent=2, ensure_ascii=False)
            
        # Verify and replace
        if is_file_accurate(temp_path, check_stderr=False):
            os.replace(temp_path, file_path)
            success_count += 1
            current_backoff = 10.0
            idx += 1
            time.sleep(0.2)
        else:
            try:
                os.remove(temp_path)
            except Exception:
                pass
            print(f"    [-] Corrupt download for game {game_id}: JSON verification failed. Retrying...")
            time.sleep(1.0)
            
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print(f"    [!] HTTPError 403 Forbidden (Rate Limit). Pausing download for {current_backoff} seconds...")
            time.sleep(current_backoff)
            current_backoff = min(current_backoff * 2, 120.0)
            continue
        else:
            print(f"    [-] HTTP error downloading game {game_id}: {e}")
            idx += 1
    except Exception as e:
        import traceback
        print(f"    [-] Error fetching game {game_id}: {e}")
        traceback.print_exc()
        idx += 1

print("=" * 80)
print(f"[+] Finished downloading test session battles:")
print(f"    - Destination: {output_dir}")
print(f"    - Total battles: {len(battles)}")
print(f"    - Downloaded successfully: {success_count}")
print(f"    - Skipped (already exists and verified): {skip_count}")
print("=" * 80)
