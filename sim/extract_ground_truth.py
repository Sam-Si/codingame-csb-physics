#!/usr/bin/env python3
"""
Ground truth extractor from authenticated battle replays.

This script mines the combination of:
- Keyframe views (official post-turn states)
- stderr PRED_ASSERT lines (bot's view of actual vs predicted)
- Actions taken

To discover the exact referee rules that are not fully documented.

The goal is 100% accurate reverse engineering of CodinGame's physics.
"""

import json
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional


@dataclass
class RefereeTransition:
    """One turn's before -> action -> after from the real referee."""
    game_id: int
    turn: int
    # State at start of turn (what bot receives for decision)
    before_pods: List[Dict]          # 4 pods, from P0/P1 lines or previous keyframe
    actions: List[Dict]              # 4 actions (pod_idx, tx, ty, thrust)
    # State after simulation (what referee actually produced)
    after_pods: List[Dict]           # from keyframe view + PRED_ASSERT actual_*
    collisions: List[Dict]
    timeouts_before: tuple
    timeouts_after: tuple


def parse_pred_assert(line: str) -> Optional[Dict]:
    if not line.startswith("PRED_ASSERT:"):
        return None
    d = {}
    for seg in line.split(";"):
        if "=" in seg:
            k, v = seg.split("=", 1)
            d[k.strip()] = v.strip()
    try:
        return {
            "turn": int(d.get("turn", -1)),
            "pod_id": int(d.get("pod_id", -1)),
            "actual_x": float(d.get("actual_x", 0)),
            "actual_y": float(d.get("actual_y", 0)),
            "actual_vx": int(float(d.get("actual_vx", 0))),
            "actual_vy": int(float(d.get("actual_vy", 0))),
            "actual_angle": float(d.get("actual_angle", 0)),  # degrees!
            "diff_x": float(d.get("diff_x", 0)),
            "diff_y": float(d.get("diff_y", 0)),
        }
    except:
        return None


def extract_transitions(battle_path: str) -> List[RefereeTransition]:
    with open(battle_path) as f:
        data = json.load(f)

    game_id = data.get("gameId")
    frames = data["frames"]

    transitions = []

    # For each game turn T, we can get:
    # - Before state: from PRED_ASSERT on the frame where bot decides for T+1, or from previous keyframe
    # - Actions: from stdout on the decision frames
    # - After state: from the keyframe after the turn + PRED_ASSERT actual_*

    num_turns = (len([f for f in frames if f.get("keyframe")]) - 1)  # rough

    for t in range(min(50, num_turns)):  # limit for now
        # Frame for player 0 decision on turn t: 2*t + 1
        # Frame for player 1 + keyframe after turn t: 2*t + 2
        f_decision = frames[2 * t + 1] if 2*t+1 < len(frames) else None
        f_after = frames[2 * t + 2] if 2*t+2 < len(frames) else None

        if not f_decision or not f_after:
            continue

        # Actions
        stdout = f_decision.get("stdout", "")
        action_lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        if len(action_lines) != 2:
            continue

        # Parse the two actions for player 0 pods 0 and 1
        # We also need player 1's actions from f_after stdout
        p1_stdout = f_after.get("stdout", "")
        p1_lines = [ln.strip() for ln in p1_stdout.splitlines() if ln.strip()]

        actions = []
        if len(action_lines) == 2:
            for pod_local, line in enumerate(action_lines):
                parts = line.split()
                actions.append({
                    "pod_idx": pod_local,   # 0 or 1
                    "tx": int(parts[0]),
                    "ty": int(parts[1]),
                    "thrust": parts[2]
                })
        if len(p1_lines) == 2:
            for pod_local, line in enumerate(p1_lines):
                parts = line.split()
                actions.append({
                    "pod_idx": 2 + pod_local,  # 2 or 3
                    "tx": int(parts[0]),
                    "ty": int(parts[1]),
                    "thrust": parts[2]
                })

        # Get after state from keyframe view (more complete)
        # For now we just record the raw view for later parsing
        after_view = f_after.get("view", "")

        # Look for PRED_ASSERT in this decision frame (these are predictions for previous turn)
        pred_lines = []
        if f_decision.get("stderr"):
            for line in f_decision["stderr"].splitlines():
                pa = parse_pred_assert(line)
                if pa and pa["turn"] == t-1:   # the assert for the turn we just finished
                    pred_lines.append(pa)

        trans = RefereeTransition(
            game_id=game_id,
            turn=t,
            before_pods=[],   # TODO: parse properly
            actions=actions,
            after_pods=[],
            collisions=[],
            timeouts_before=(0,0),
            timeouts_after=(0,0),
        )
        transitions.append(trans)

    return transitions


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python sim/extract_ground_truth.py battles/.../battle_XXX.json")
        sys.exit(1)

    trans = extract_transitions(sys.argv[1])
    print(f"Extracted {len(trans)} transitions (stub)")
