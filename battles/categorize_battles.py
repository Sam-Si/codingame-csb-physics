#!/usr/bin/env python3
"""
Categorize leaderboard battles (gameId > THRESHOLD) into observation-based folders.

Usage:
    python battles/categorize_battles.py

Outputs:
    battles/leaderboard_battles_categorized/
        01_...19_.../   category folders with copied battle_*.json
        manifest.csv    per-battle labels
        README.md       category documentation
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "leaderboard_battles"
OUT = ROOT / "leaderboard_battles_categorized"
THRESHOLD = 870230019

CATEGORIES = {
    "01_agent_program_timeout":
        "Agent program timeout — bot failed to output 2 lines in time (CodinGame agent timeout).",
    "02_invalid_input_abort":
        "Invalid input abort — bot sent illegal thrust/power (e.g. power > 200). Very short games.",
    "03_double_elimination":
        "Double elimination — both players eliminated (rare).",
    "04_max_rounds_stalemate":
        "Max rounds reached — neither player finished before the turn/frame limit.",
    "05_end_reached_with_elimination":
        "End reached + elimination — race finished but summary also marks a player eliminated.",
    "06_end_reached_marathon":
        "Marathon finish — endReached with 300+ game turns. Long-horizon physics stress tests.",
    "07_end_reached_sprint":
        "Sprint finish — endReached in under 80 game turns. Fast decisive races.",
    "08_end_reached_collision_fest":
        "Collision-heavy finish — endReached with >80 pod-pod collisions. Bounce/impulse tests.",
    "09_end_reached_shield_heavy":
        "Shield-heavy finish — endReached with 20+ SHIELD commands. Shield/mass interactions.",
    "10_end_reached_boost_heavy":
        "Boost-heavy finish — endReached with 4+ BOOST commands (not already in more specific buckets).",
    "11_end_reached_standard":
        "Standard finish — normal endReached without special traits above. Baseline replays.",
    "12_early_pod_timeout":
        "Early pod timeout — eliminated by missing checkpoints in <30 game turns.",
    "13_elim_after_collision_battle":
        "Elimination after collision battle — pod timeout after >50 collisions (blocking/ramming).",
    "14_elim_shield_war":
        "Elimination after shield war — pod timeout with 15+ SHIELD uses.",
    "15_elim_pod_timeout_standard":
        "Standard pod timeout elimination — checkpoint timer hit 0 without special traits above.",
    "16_aborted_very_short":
        "Aborted very short — <5 game turns without classified agent/invalid/end/elim pattern.",
    "17_other_unknown_outcome":
        "Other / unknown — does not match classified outcome patterns.",
    "18_timeout_yes_any":
        "META mirror: any timeout (agent program OR pod/checkpoint elimination).",
    "19_timeout_no_clean_finish":
        "META mirror: clean endReached without elimination/agent-timeout/invalid.",
}


def game_turns(n_frames: int) -> int:
    return max(0, (n_frames - 1) // 2)


def count_collisions(frames) -> int:
    n = 0
    for fr in frames:
        if fr.get("keyframe") and fr.get("view"):
            for ln in fr["view"].split("\n"):
                if re.match(r"^\d+ \d+\.\d+", ln.strip()):
                    n += 1
    return n


def analyze(data: dict) -> dict:
    frames = data.get("frames", [])
    last = frames[-1] if frames else {}
    summary = last.get("summary") or ""
    all_gi = "\n".join((fr.get("gameInformation") or "") for fr in frames)
    all_view = "\n".join((fr.get("view") or "") for fr in frames if fr.get("keyframe"))
    all_stdout = "\n".join((fr.get("stdout") or "") for fr in frames)

    n_frames = len(frames)
    gt = game_turns(n_frames)
    n_col = count_collisions(frames)
    boost_count = len(re.findall(r"\bBOOST\b", all_stdout))
    shield_count = len(re.findall(r"\bSHIELD\b", all_stdout))

    agent_timeout = "Timeout: the program did not provide" in all_gi
    invalid_input = "invalid input" in all_gi.lower() or "InvalidInput" in all_view
    pod_timeout_msg = "did not reach the next checkpoint in time" in all_gi
    end_reached = "End reached" in summary or "endReached" in all_view
    max_rounds = "Max rounds reached" in summary
    p0_elim = "$0 eliminated" in summary
    p1_elim = "$1 eliminated" in summary
    double_elim = p0_elim and p1_elim

    ranks = data.get("ranks", [])
    winner = None
    if ranks and len(ranks) >= 2:
        if ranks[0] < ranks[1]:
            winner = 0
        elif ranks[1] < ranks[0]:
            winner = 1

    if agent_timeout:
        primary = "01_agent_program_timeout"
    elif invalid_input:
        primary = "02_invalid_input_abort"
    elif double_elim:
        primary = "03_double_elimination"
    elif max_rounds:
        primary = "04_max_rounds_stalemate"
    elif end_reached and (p0_elim or p1_elim):
        primary = "05_end_reached_with_elimination"
    elif end_reached and gt >= 300:
        primary = "06_end_reached_marathon"
    elif end_reached and gt < 80:
        primary = "07_end_reached_sprint"
    elif end_reached and n_col > 80:
        primary = "08_end_reached_collision_fest"
    elif end_reached and shield_count >= 20:
        primary = "09_end_reached_shield_heavy"
    elif end_reached and boost_count >= 4:
        primary = "10_end_reached_boost_heavy"
    elif end_reached:
        primary = "11_end_reached_standard"
    elif pod_timeout_msg or p0_elim or p1_elim:
        if gt < 30:
            primary = "12_early_pod_timeout"
        elif n_col > 50:
            primary = "13_elim_after_collision_battle"
        elif shield_count >= 15:
            primary = "14_elim_shield_war"
        else:
            primary = "15_elim_pod_timeout_standard"
    elif gt < 5:
        primary = "16_aborted_very_short"
    else:
        primary = "17_other_unknown_outcome"

    is_timeout = bool(
        agent_timeout
        or pod_timeout_msg
        or primary in {
            "01_agent_program_timeout",
            "12_early_pod_timeout",
            "13_elim_after_collision_battle",
            "14_elim_shield_war",
            "15_elim_pod_timeout_standard",
        }
        or ((p0_elim or p1_elim) and not end_reached)
    )
    is_clean_finish = end_reached and not (p0_elim or p1_elim or agent_timeout or invalid_input)

    timeout_type = (
        "agent_program" if agent_timeout
        else "pod_checkpoint" if (
            pod_timeout_msg or ((p0_elim or p1_elim) and not end_reached and not invalid_input)
        )
        else "none"
    )

    return {
        "primary": primary,
        "is_timeout": is_timeout,
        "is_clean_finish": is_clean_finish,
        "agent_timeout": agent_timeout,
        "invalid_input": invalid_input,
        "end_reached": end_reached,
        "max_rounds": max_rounds,
        "p0_elim": p0_elim,
        "p1_elim": p1_elim,
        "game_turns": gt,
        "n_frames": n_frames,
        "n_collisions": n_col,
        "boost_count": boost_count,
        "shield_count": shield_count,
        "winner": winner,
        "ranks": ranks,
        "scores": data.get("scores", []),
        "summary_tail": summary.replace("\n", " | ")[:160],
        "timeout_type": timeout_type,
    }


def ensure_dir(path: Path) -> Path:
    """Create a category directory only when we are about to write into it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    # Do not pre-create category folders — only non-empty ones are written below.

    files = sorted(SRC.glob("battle_*.json"))
    selected = [
        f for f in files
        if (m := re.search(r"battle_(\d+)", f.name)) and int(m.group(1)) > THRESHOLD
    ]
    print(f"After threshold {THRESHOLD}: {len(selected)} battles")

    primary_counts: Counter = Counter()
    timeout_counts: Counter = Counter()
    manifest_rows = []

    for i, fpath in enumerate(selected):
        with open(fpath) as fh:
            data = json.load(fh)
        info = analyze(data)
        primary = info["primary"]
        primary_counts[primary] += 1
        timeout_counts["timeout_yes" if info["is_timeout"] else "timeout_no"] += 1

        shutil.copy2(fpath, ensure_dir(OUT / primary) / fpath.name)
        if info["is_timeout"]:
            shutil.copy2(fpath, ensure_dir(OUT / "18_timeout_yes_any") / fpath.name)
        if info["is_clean_finish"]:
            shutil.copy2(fpath, ensure_dir(OUT / "19_timeout_no_clean_finish") / fpath.name)

        manifest_rows.append({
            "game_id": data.get("gameId", fpath.stem.replace("battle_", "")),
            "filename": fpath.name,
            "primary_category": primary,
            "is_timeout": info["is_timeout"],
            "timeout_type": info["timeout_type"],
            "is_clean_finish": info["is_clean_finish"],
            "end_reached": info["end_reached"],
            "max_rounds": info["max_rounds"],
            "invalid_input": info["invalid_input"],
            "p0_elim": info["p0_elim"],
            "p1_elim": info["p1_elim"],
            "winner": info["winner"],
            "game_turns": info["game_turns"],
            "n_frames": info["n_frames"],
            "n_collisions": info["n_collisions"],
            "boost_count": info["boost_count"],
            "shield_count": info["shield_count"],
            "summary_tail": info["summary_tail"],
        })
        if (i + 1) % 3000 == 0:
            print(f"  {i + 1}/{len(selected)}")

    with open(OUT / "manifest.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(manifest_rows[0].keys()))
        writer.writeheader()
        writer.writerows(manifest_rows)

    clean_n = sum(1 for r in manifest_rows if r["is_clean_finish"])
    lines = [
        "# Leaderboard Battles — Categorized",
        "",
        f"**Filter:** only battles strictly after `battle_{THRESHOLD}.json` (id > {THRESHOLD}).",
        f"**Source:** `{SRC}`  |  **Total:** {len(selected)}",
        "",
        "Only non-empty category folders are created (empty outcome classes are omitted).",
        "",
        "## Timeout labels",
        "",
        f"| Label | Count | Where |",
        f"|-------|------:|-------|",
        f"| timeout_yes | {timeout_counts.get('timeout_yes', 0)} | primary elim/agent folders + `18_timeout_yes_any/` |",
        f"| timeout_no | {timeout_counts.get('timeout_no', 0)} | all other primaries |",
        f"| clean finish (subset of no-timeout) | {clean_n} | `19_timeout_no_clean_finish/` |",
        "",
        "Timeout types in `manifest.csv` → `timeout_type` column:",
        "- `agent_program` — bot failed to print output in time",
        "- `pod_checkpoint` — in-game 100-turn checkpoint timer reached 0 (player eliminated)",
        "- `none` — no timeout",
        "",
        "Note: agent program timeouts are usually pre-segregated in `battles/leaderboard_timeouts/`",
        "by the scraper, so that primary folder is omitted when the slice has none.",
        "",
        "## Primary categories present in this slice (mutually exclusive, priority order)",
        "",
        "| # | Folder | Count | Description |",
        "|--:|--------|------:|-------------|",
    ]
    idx = 0
    for cat, desc in CATEGORIES.items():
        if cat.startswith(("18_", "19_")):
            continue
        count = primary_counts.get(cat, 0)
        if count == 0:
            continue  # omit empty categories from docs and disk
        idx += 1
        lines.append(f"| {idx} | `{cat}/` | {count} | {desc} |")

    lines += [
        "",
        "## META mirror folders (additional copies)",
        "",
        f"| Folder | Count | Description |",
        f"|--------|------:|-------------|",
        f"| `18_timeout_yes_any/` | {timeout_counts.get('timeout_yes', 0)} | All timeout-related battles |",
        f"| `19_timeout_no_clean_finish/` | {clean_n} | Clean endReached only |",
        "",
        "## Files",
        "",
        "- `manifest.csv` — per-battle labels and metrics",
        "- `../categorize_battles.py` — re-runnable script",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(lines))

    print("\n=== Primary counts (non-empty only) ===")
    for cat in CATEGORIES:
        if cat.startswith(("18_", "19_")):
            continue
        n = primary_counts.get(cat, 0)
        if n:
            print(f"  {n:6d}  {cat}")
    print("Timeout:", dict(timeout_counts))
    print("Done ->", OUT)


if __name__ == "__main__":
    main()
