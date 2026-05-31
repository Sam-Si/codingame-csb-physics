#!/usr/bin/env python3
"""
Validator / analyzer for Coders Strike Back physics using real battle replays.

Usage:
    python sim/validate.py battles/test_session_battles/battle_891669739.json

Current capabilities:
- Loads the complete move history for all 4 pods + ground truth states.
- Reports summary, turns with BOOST/SHIELD, collision turns.
- Extracts the bot's own PRED_ASSERT diagnostics (shows current predictor accuracy).
- Prepares structured data for feeding into a physics engine (Python or C++ driver).

Future:
- Step-by-step comparison against python_sim.Simulator or compiled C++ physics/replay_driver
- Detailed per-component diff reports (x,y,vx,vy,angle,next_cp,timeout)
- Automatic minimization to the first diverging turn.
"""

from __future__ import annotations
import sys
import json
from collections import Counter, defaultdict
from battle_parser import load_battle, BattleLog, TurnActions, GameState


def analyze_battle(log: BattleLog):
    print("=" * 70)
    print(f"BATTLE {log.game_id}  —  {len(log.turns)} turns played")
    print("=" * 70)
    print(f"Checkpoints ({len(log.checkpoints)}): {log.checkpoints}")
    print(f"Final ranks (0=winner): {log.ranks}")
    if log.tooltips:
        print(f"Events: {log.tooltips}")
    print()

    # Collect interesting events
    boosts = []
    shields = []
    collisions_per_turn: dict[int, int] = defaultdict(int)
    pred_diffs = []  # (turn, pod_id, diff_x, diff_y, diff_vx, diff_vy, diff_angle)

    for t, ta in enumerate(log.turns):
        actions = [
            ("p0_pod0", ta.p0_pod0),
            ("p0_pod1", ta.p0_pod1),
            ("p1_pod0", ta.p1_pod0),
            ("p1_pod1", ta.p1_pod1),
        ]
        for name, a in actions:
            if a.thrust == "BOOST":
                boosts.append((t, name, a.target_x, a.target_y))
            if a.thrust == "SHIELD":
                shields.append((t, name, a.target_x, a.target_y))

    for kf in log.keyframes:
        if kf.collisions:
            collisions_per_turn[kf.game_turn] = len(kf.collisions)

    # Parse PRED_ASSERT from the raw frames (they live in agent-0 frames)
    frames = log.raw.get("frames", [])
    for i, fr in enumerate(frames):
        if not fr.get("stderr"):
            continue
        for line in fr["stderr"].splitlines():
            if line.startswith("PRED_ASSERT:"):
                # PRED_ASSERT:turn=0;pod_id=0;...;diff_x=0.00;diff_y=0.00;...
                parts = {}
                for seg in line.split(";"):
                    if "=" in seg:
                        k, v = seg.split("=", 1)
                        parts[k.strip()] = v.strip()
                try:
                    turn = int(parts.get("turn", -1))
                    pod = int(parts.get("pod_id", -1))
                    dx = float(parts.get("diff_x", 0))
                    dy = float(parts.get("diff_y", 0))
                    dvx = float(parts.get("diff_vx", 0))
                    dvy = float(parts.get("diff_vy", 0))
                    dangle = float(parts.get("diff_angle", 0))
                    if abs(dx) > 0 or abs(dy) > 0 or abs(dvx) > 0 or abs(dvy) > 0 or abs(dangle) > 0.01:
                        pred_diffs.append((turn, pod, dx, dy, dvx, dvy, dangle))
                except Exception:
                    pass

    # Report
    print(f"BOOST usages: {len(boosts)}")
    for t, name, tx, ty in boosts[:8]:
        print(f"  turn {t:3d} {name:8s} -> ({tx},{ty})")
    if len(boosts) > 8:
        print(f"  ... and {len(boosts)-8} more")

    print(f"\nSHIELD usages: {len(shields)}")
    for t, name, tx, ty in shields[:8]:
        print(f"  turn {t:3d} {name:8s} -> ({tx},{ty})")
    if len(shields) > 8:
        print(f"  ... and {len(shields)-8} more")

    coll_turns = sorted(collisions_per_turn.keys())
    print(f"\nTurns with recorded collisions: {len(coll_turns)}")
    if coll_turns:
        print("  ", coll_turns[:20], "..." if len(coll_turns) > 20 else "")

    print(f"\nNon-zero PRED_ASSERT diffs logged by bot: {len(pred_diffs)}")
    if pred_diffs:
        # Show the worst ones
        worst = sorted(pred_diffs, key=lambda d: abs(d[2])+abs(d[3])+abs(d[4])+abs(d[5]), reverse=True)[:10]
        print("  Worst position/vel prediction errors (turn, pod, dx,dy,dvx,dvy,dang):")
        for item in worst:
            print(f"    {item}")

    # Final state comparison helper data
    print("\n" + "-" * 70)
    print("Last 3 keyframe states (ground truth from referee):")
    for kf in log.keyframes[-3:]:
        print(f"  After turn {kf.game_turn:3d} (frame {kf.frame_index}):")
        for i, p in enumerate(kf.pods):
            print(f"    pod{i}: ({p.x:7.1f},{p.y:7.1f}) v=({p.vx:4d},{p.vy:4d}) "
                  f"next={p.next_cp} shield_t={p.shield_active} boosted={p.boosted}")
        print(f"         timeouts: p0={kf.timeout_p0} p1={kf.timeout_p1}")

    print("\nReady for physics replay validation.")
    print("Next steps: feed log.turns (the 4 actions per turn) + initial pods into your engine.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python sim/validate.py <battle.json>")
        print("Example: python sim/validate.py battles/test_session_battles/battle_891669739.json")
        sys.exit(1)

    path = sys.argv[1]
    log = load_battle(path)
    analyze_battle(log)


if __name__ == "__main__":
    main()
