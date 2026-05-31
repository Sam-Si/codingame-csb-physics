"""
Battle log parser for Coders Strike Back test session replays.

Parses the raw JSON from /services/gameResult/findByGameId into structured data
for deterministic physics replay validation.

Handles all battle types:
- Normal games (elimination by timeout)
- endReached games (a pod completed the race)
- Short/crashed games (one player timed out or produced invalid output)
- Games where one or both players produced no output on some turns
"""

from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any


@dataclass
class PodState:
    x: float
    y: float
    vx: int
    vy: int
    thrust: int
    shield_active: int
    target_x: Optional[int]
    target_y: Optional[int]
    angle: Optional[float]
    boosted: int
    next_cp: int
    z_order: int


@dataclass
class Action:
    target_x: int
    target_y: int
    thrust: str


@dataclass
class TurnActions:
    turn: int
    p0_pod0: Action
    p0_pod1: Action
    p1_pod0: Action
    p1_pod1: Action


@dataclass
class CollisionEvent:
    collision_id: int
    t: float
    pod_a: int
    pod_a_x: int
    pod_a_y: int
    pod_b: int
    pod_b_x: int
    pod_b_y: int
    impact_force: float
    impulse_x: int
    impulse_y: int


@dataclass
class GameState:
    frame_index: int
    game_turn: int
    pods: List[PodState] = field(default_factory=list)
    timeout_p0: int = 100
    timeout_p1: int = 100
    progress_p0: float = 1.0
    progress_p1: float = 1.0
    collisions: List[CollisionEvent] = field(default_factory=list)
    end_reached: bool = False


@dataclass
class BattleLog:
    game_id: int
    laps: int = 3
    checkpoints: List[Tuple[int, int]] = field(default_factory=list)
    initial_state: GameState = field(default_factory=lambda: GameState(frame_index=0, game_turn=-1))
    turns: List[TurnActions] = field(default_factory=list)
    keyframes: List[GameState] = field(default_factory=list)
    ranks: List[int] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)
    tooltips: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    # Derived outcome
    winner: int = -1           # 0 or 1 (player index), -1 = unknown
    end_reason: str = ""       # "race", "elimination", "timeout_crash", "unknown"
    total_game_turns: int = 0


def _parse_frame_number(first_token: str) -> int:
    """Parse frame number, handling '414 endReached' style."""
    return int(first_token.split()[0])


def parse_view(view: str) -> Dict[str, Any]:
    """Parse a 'view' string from a keyframe."""
    lines = [ln.strip() for ln in view.strip().split("\n") if ln.strip()]
    if not lines:
        return {}

    result: Dict[str, Any] = {}

    # Frame number line can be "414 endReached", "76 InvalidInput", or just "414"
    first_line = lines[0]
    if "endReached" in first_line:
        result["end_reached"] = True
        result["frame"] = int(first_line.split()[0])
    elif "InvalidInput" in first_line:
        result["end_reached"] = False
        result["invalid_input"] = True
        result["frame"] = int(first_line.split()[0])
    else:
        result["end_reached"] = False
        try:
            result["frame"] = int(first_line)
        except ValueError:
            return result

    if len(lines) == 1:
        return result

    # Frame 0 has "CodersStrikeBack" header
    is_init_frame = len(lines) > 1 and "CodersStrikeBack" in lines[1]

    if is_init_frame:
        result["game"] = lines[1]
        result["constants"] = lines[2]
        result["checkpoints"] = lines[3]
        result["spawns"] = lines[4]
        pod_start = 5
    else:
        pod_start = 1

    # Pod blocks: state line + quoted message line, repeated 4 times
    pods = []
    i = pod_start
    while i + 1 < len(lines):
        state_line = lines[i]
        msg_line = lines[i + 1]
        # Stop if we hit timeout line or non-pod data
        if state_line.startswith(("1:", "2:", "0:")):
            break
        # Pod state lines start with a float (the x position)
        first_char = state_line[0]
        if not (first_char.isdigit() or first_char == '-' or first_char == '.'):
            break
        # Quick sanity: must have enough fields
        parts = state_line.split()
        if len(parts) < 12:
            break
        pods.append({"state": state_line, "message": msg_line})
        i += 2

    result["pods_raw"] = pods

    # Remaining lines: timeout + optional collisions
    remaining = lines[i:]
    result["remaining_lines"] = remaining

    if remaining:
        timeout_line = remaining[0]
        m = re.match(r"(\d+):([-\d]+)\s+(\d+):([-\d]+)", timeout_line)
        if m:
            result["timeout_p0"] = int(m.group(2))
            result["progress_p0"] = int(m.group(1))
            result["timeout_p1"] = int(m.group(4))
            result["progress_p1"] = int(m.group(3))

        collisions = []
        for cl in remaining[1:]:
            parts = cl.split()
            if len(parts) >= 11:
                try:
                    collisions.append(CollisionEvent(
                        collision_id=int(parts[0]),
                        t=float(parts[1]),
                        pod_a=int(parts[2]),
                        pod_a_x=int(parts[3]),
                        pod_a_y=int(parts[4]),
                        pod_b=int(parts[5]),
                        pod_b_x=int(parts[6]),
                        pod_b_y=int(parts[7]),
                        impact_force=float(parts[8]),
                        impulse_x=int(parts[9]),
                        impulse_y=int(parts[10]),
                    ))
                except ValueError:
                    pass
        result["collisions"] = collisions

    return result


def parse_pod_state(state_line: str) -> PodState:
    parts = state_line.split()
    return PodState(
        x=float(parts[0]),
        y=float(parts[1]),
        vx=int(parts[2]),
        vy=int(parts[3]),
        thrust=int(parts[4]),
        shield_active=int(parts[5]),
        target_x=None if parts[6] == "null" else int(parts[6]),
        target_y=None if parts[7] == "null" else int(parts[7]),
        angle=None if parts[8] == "null" else float(parts[8]),
        boosted=int(parts[9]),
        next_cp=int(parts[10]),
        z_order=int(parts[11]),
    )


def parse_action_line(line: str) -> Optional[Action]:
    """Parse one action line. Returns None if unparseable."""
    parts = line.strip().split()
    if len(parts) < 3:
        return None
    try:
        tx = int(parts[0])
        ty = int(parts[1])
        thrust = parts[2]
        return Action(tx, ty, thrust)
    except ValueError:
        return None


def _get_stdout_actions(frame: Dict, expected: int = 2) -> List[Optional[Action]]:
    """Parse stdout into a list of Actions. Returns list of length `expected`, with None for missing."""
    stdout = frame.get("stdout") or ""
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    result: List[Optional[Action]] = []
    for i in range(expected):
        if i < len(lines):
            result.append(parse_action_line(lines[i]))
        else:
            result.append(None)
    return result


def parse_checkpoints_from_referee(referee_input: str) -> List[Tuple[int, int]]:
    for line in referee_input.strip().splitlines():
        if line.startswith("map="):
            nums = [int(x) for x in line.split("=", 1)[1].split()]
            return list(zip(nums[0::2], nums[1::2]))
    return []


def load_battle(path: str) -> BattleLog:
    """Load and fully parse a battle JSON file, handling all edge cases."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    game_id = raw.get("gameId") or raw.get("id", 0)
    frames: List[Dict[str, Any]] = raw.get("frames", [])

    # Checkpoints from refereeInput (always reliable)
    cps = parse_checkpoints_from_referee(raw.get("refereeInput", ""))
    if not cps and frames:
        parsed0 = parse_view(frames[0]["view"])
        cp_line = parsed0.get("checkpoints", "")
        if cp_line:
            nums = [int(x) for x in cp_line.split()]
            cps = list(zip(nums[0::2], nums[1::2]))

    # Initial state from frame 0
    init_state = GameState(frame_index=0, game_turn=-1)
    if frames:
        view_data = parse_view(frames[0]["view"])
        for pr in view_data.get("pods_raw", []):
            init_state.pods.append(parse_pod_state(pr["state"]))
        init_state.timeout_p0 = view_data.get("timeout_p0", 100)
        init_state.timeout_p1 = view_data.get("timeout_p1", 100)

    # Extract all complete turns — a turn needs both players' valid stdout (2 lines each)
    # AND a resulting keyframe with 4 pods.
    turns: List[TurnActions] = []
    keyframes: List[GameState] = []

    t = 0
    while True:
        f_p0_idx = 2 * t + 1
        f_p1_idx = 2 * t + 2
        if f_p1_idx >= len(frames):
            break

        f_p0 = frames[f_p0_idx]
        f_p1 = frames[f_p1_idx]

        # Parse actions from both players
        p0_actions = _get_stdout_actions(f_p0, 2)
        p1_actions = _get_stdout_actions(f_p1, 2)

        # All 4 actions must be present for a valid turn
        if any(a is None for a in p0_actions) or any(a is None for a in p1_actions):
            break

        # Parse the keyframe for the after-turn state
        view_str = f_p1.get("view", "")
        vdata = parse_view(view_str)
        pods_raw = vdata.get("pods_raw", [])
        if len(pods_raw) != 4:
            break

        turns.append(TurnActions(
            turn=t,
            p0_pod0=p0_actions[0],
            p0_pod1=p0_actions[1],
            p1_pod0=p1_actions[0],
            p1_pod1=p1_actions[1],
        ))

        gs = GameState(frame_index=f_p1_idx, game_turn=t)
        for pr in pods_raw:
            gs.pods.append(parse_pod_state(pr["state"]))
        gs.timeout_p0 = vdata.get("timeout_p0", 0)
        gs.timeout_p1 = vdata.get("timeout_p1", 0)
        gs.progress_p0 = vdata.get("progress_p0", 0)
        gs.progress_p1 = vdata.get("progress_p1", 0)
        gs.collisions = vdata.get("collisions", [])
        gs.end_reached = vdata.get("end_reached", False)
        keyframes.append(gs)

        t += 1

    # Determine expected outcome from ranks
    ranks = raw.get("ranks", [])
    winner = -1
    if len(ranks) >= 2:
        # ranks[i] = the rank of player i (0 = winner)
        if ranks[0] < ranks[1]:
            winner = 0
        elif ranks[1] < ranks[0]:
            winner = 1

    # End reason
    tooltips = raw.get("tooltips") or []
    end_reason = "unknown"
    for tip in tooltips:
        if "did not reach the next checkpoint" in tip:
            end_reason = "elimination"
            break
        if "timeout" in tip.lower():
            end_reason = "timeout_crash"
            break
    if end_reason == "unknown" and keyframes and keyframes[-1].end_reached:
        end_reason = "race"

    log = BattleLog(
        game_id=game_id,
        checkpoints=cps,
        initial_state=init_state,
        turns=turns,
        keyframes=keyframes,
        ranks=ranks,
        scores=raw.get("scores", []),
        tooltips=tooltips,
        raw=raw,
        winner=winner,
        end_reason=end_reason,
        total_game_turns=len(turns),
    )
    return log
