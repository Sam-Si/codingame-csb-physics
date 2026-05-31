#!/usr/bin/env python3
"""
Turn-by-turn physics accuracy verifier for Coders Strike Back.

Usage (from project root):
    python sim/verify_battles.py battles/test_session_battles

For each battle JSON it:
- Loads the ground-truth initial state + all player actions + referee keyframes
- Feeds the exact starting state and exact actions into the C++ physics engine
- Compares the engine's output against the referee state EVERY TURN
- Reports the first turn where the physics diverges (if any)

This is the definitive test for physics accuracy: if all turns of all battles match,
your physics engine is 100% faithful to the CodinGame referee.
"""

import os
import sys
import math
import glob
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from battle_parser import load_battle
from physics_driver import CppPhysics, ensure_driver_built, _DEFAULT_DRIVER


# ---------------------------------------------------------------------------
# Tolerances for state comparison
# ---------------------------------------------------------------------------
POS_TOL = 1.0     # position: within 1 unit (rounding)
VEL_TOL = 1       # velocity: within 1 unit (trunc rounding)
ANG_TOL_DEG = 1.0 # angle: within 1 degree


def pos_close(a, b):
    return abs(a - b) <= POS_TOL

def vel_close(a, b):
    return abs(a - b) <= VEL_TOL

def angle_close(a_rad, b_rad):
    da = abs(a_rad - b_rad)
    da = min(da, 2 * math.pi - da)
    return da <= (ANG_TOL_DEG * math.pi / 180.0)


def _is_invalid_thrust(thrust_str):
    """Check if a single thrust value is invalid (negative or > 200).
    Both cases: referee skips rotation and applies 0 thrust.
    Difference: negative activates shield, >200 does not."""
    if thrust_str in ("SHIELD", "BOOST"):
        return False
    try:
        val = int(thrust_str)
        return val < 0 or val > 200
    except (ValueError, TypeError):
        return False


def compare_turn(sim_pods, gt_pods, sim_timeouts, gt_timeouts, n_checkpoints=0):
    """Compare simulation output for one turn against ground-truth keyframe.
    Returns list of mismatch strings (empty = perfect match).
    n_checkpoints: number of base checkpoints (for modular next_cp comparison)."""
    errs = []
    for i in range(4):
        sp = sim_pods[i]
        gp = gt_pods[i]

        if not (pos_close(sp["x"], gp.x) and pos_close(sp["y"], gp.y)):
            errs.append(f"pod{i} pos sim=({sp['x']:.0f},{sp['y']:.0f}) gt=({gp.x:.0f},{gp.y:.0f}) "
                        f"Δ=({sp['x']-gp.x:.1f},{sp['y']-gp.y:.1f})")

        if not (vel_close(sp["vx"], gp.vx) and vel_close(sp["vy"], gp.vy)):
            errs.append(f"pod{i} vel sim=({sp['vx']},{sp['vy']}) gt=({gp.vx},{gp.vy})")

        gt_angle = gp.angle if gp.angle is not None else 0.0
        if not angle_close(sp["angle"], gt_angle):
            errs.append(f"pod{i} angle sim={math.degrees(sp['angle']):.1f}° gt={math.degrees(gt_angle):.1f}°")

        # Compare next_cp with modular wrapping: the referee shows next_cp % n_checkpoints,
        # but the engine uses a linear index across all laps.
        sim_cp = sp["next"] % n_checkpoints if n_checkpoints > 0 else sp["next"]
        if sim_cp != gp.next_cp:
            errs.append(f"pod{i} next_cp sim={sp['next']}(mod={sim_cp}) gt={gp.next_cp}")

    if sim_timeouts != gt_timeouts:
        errs.append(f"timeouts sim={sim_timeouts} gt={gt_timeouts}")

    return errs


def run_battle(phys, log):
    """Run a full battle turn-by-turn.
    Returns (first_fail_turn, first_fail_errors, total_turns_checked, perfect_turns).
    If first_fail_turn is None, all turns matched.
    """
    # Inject initial state
    init = log.initial_state
    for i, p in enumerate(init.pods):
        ang = p.angle if p.angle is not None else -0.0174533
        phys.set_pod(i, p.x, p.y, p.vx, p.vy, ang, p.next_cp, p.shield_active, p.boosted)
    phys.set_timeouts(init.timeout_p0, init.timeout_p1)

    first_fail_turn = None
    first_fail_errors = []
    perfect = 0

    for t_idx, ta in enumerate(log.turns):
        if t_idx >= len(log.keyframes):
            break  # no ground truth for this turn

        # InvalidInput rule (verified from battle data):
        # - If a player's FIRST pod action has invalid thrust → BOTH pods invalidated
        # - If only the SECOND pod action is invalid → only that pod invalidated
        # The referee reads stdout line by line; error on line 1 stops parsing entirely.
        p0_acts = [(ta.p0_pod0.target_x, ta.p0_pod0.target_y, ta.p0_pod0.thrust),
                   (ta.p0_pod1.target_x, ta.p0_pod1.target_y, ta.p0_pod1.thrust)]
        p1_acts = [(ta.p1_pod0.target_x, ta.p1_pod0.target_y, ta.p1_pod0.thrust),
                   (ta.p1_pod1.target_x, ta.p1_pod1.target_y, ta.p1_pod1.thrust)]

        if _is_invalid_thrust(p0_acts[0][2]):
            # First line invalid → both pods invalidated.
            # Propagate the same invalid value so C++ engine applies correct behavior
            # (negative = shield, >200 = no shield).
            inv = p0_acts[0][2]
            p0_acts = [(p0_acts[0][0], p0_acts[0][1], inv),
                       (p0_acts[1][0], p0_acts[1][1], inv)]
        elif _is_invalid_thrust(p0_acts[1][2]):
            pass  # only second pod invalidated, keep original value for C++ engine

        if _is_invalid_thrust(p1_acts[0][2]):
            inv = p1_acts[0][2]
            p1_acts = [(p1_acts[0][0], p1_acts[0][1], inv),
                       (p1_acts[1][0], p1_acts[1][1], inv)]
        elif _is_invalid_thrust(p1_acts[1][2]):
            pass  # only second pod invalidated, keep original value for C++ engine

        phys.apply(0, p0_acts[0][0], p0_acts[0][1], p0_acts[0][2])
        phys.apply(1, p0_acts[1][0], p0_acts[1][1], p0_acts[1][2])
        phys.apply(2, p1_acts[0][0], p1_acts[0][1], p1_acts[0][2])
        phys.apply(3, p1_acts[1][0], p1_acts[1][1], p1_acts[1][2])

        sim = phys.step()
        if len(sim["pods"]) < 4:
            if first_fail_turn is None:
                first_fail_turn = t_idx
                first_fail_errors = [f"driver returned {len(sim['pods'])} pods instead of 4"]
            break

        gt = log.keyframes[t_idx]
        gt_timeouts = (gt.timeout_p0, gt.timeout_p1)

        errs = compare_turn(sim["pods"], gt.pods, sim["timeouts"], gt_timeouts,
                            n_checkpoints=len(log.checkpoints))
        if errs:
            if first_fail_turn is None:
                first_fail_turn = t_idx
                first_fail_errors = errs
            break  # stop at first divergence — later turns are meaningless
        else:
            perfect += 1

    return first_fail_turn, first_fail_errors, min(len(log.turns), len(log.keyframes)), perfect


def main():
    if len(sys.argv) < 2:
        print("Usage: python sim/verify_battles.py <directory_of_battles>")
        print("Example: python sim/verify_battles.py battles/test_session_battles")
        sys.exit(1)

    battle_dir = sys.argv[1]
    # Support both flat directory and recursive search
    files = sorted(glob.glob(os.path.join(battle_dir, "battle_*.json")))
    if not files:
        files = sorted(glob.glob(os.path.join(battle_dir, "**", "battle_*.json"), recursive=True))

    print(f"Verifying {len(files)} battles in {battle_dir}...")

    # Build driver if needed
    driver_path = ensure_driver_built()

    passed = 0
    failed = 0
    skipped = 0
    total_turns = 0
    total_perfect_turns = 0
    fail_details = []        # (name, fail_turn, n_turns, first_err, all_errs)
    fail_turn_histogram = {} # turn -> count
    start_time = time.time()

    for path in files:
        name = os.path.basename(path)
        try:
            log = load_battle(path)

            n_turns = min(len(log.turns), len(log.keyframes))
            if n_turns == 0:
                skipped += 1
                continue

            total_turns += n_turns

            phys = CppPhysics(driver_path)
            phys.init_battle(log.checkpoints, laps=log.laps)

            fail_turn, fail_errs, checked, perfect = run_battle(phys, log)
            phys.close()

            total_perfect_turns += perfect

            if fail_turn is None:
                passed += 1
            else:
                failed += 1
                errs_str = "; ".join(fail_errs[:3])
                detail = f"FAIL: {name} turn {fail_turn}/{n_turns} — {errs_str}"
                fail_details.append((name, fail_turn, n_turns, fail_errs))
                fail_turn_histogram[fail_turn] = fail_turn_histogram.get(fail_turn, 0) + 1
                print(detail)

        except Exception as e:
            skipped += 1
            print(f"SKIP: {name} ({e})")

    elapsed = time.time() - start_time

    print(f"\n{'='*60}")
    print(f"=== Verification Results ===")
    print(f"{'='*60}")
    print(f"Total battles:    {len(files)}")
    print(f"Passed (100%):    {passed}")
    print(f"Failed:           {failed}")
    print(f"Skipped:          {skipped}")
    print(f"")
    print(f"Total turns:      {total_turns}")
    print(f"Perfect turns:    {total_perfect_turns}")
    if total_turns > 0:
        print(f"Turn accuracy:    {total_perfect_turns/total_turns*100:.2f}%")
    print(f"")
    print(f"Time:             {elapsed:.3f} seconds")
    if elapsed > 0:
        print(f"Battle rate:      {len(files)/elapsed:.1f} battles/sec")
        print(f"Turn rate:        {total_turns/elapsed:.0f} turns/sec")

    if failed:
        print(f"\n*** {failed} BATTLES FAILED ***")

        # Failure breakdown by first-divergence turn
        print(f"\nFirst divergence distribution:")
        t0_fails = sum(1 for _, ft, _, _ in fail_details if ft == 0)
        t1_fails = sum(1 for _, ft, _, _ in fail_details if ft == 1)
        t2_fails = sum(1 for _, ft, _, _ in fail_details if ft == 2)
        early = sum(1 for _, ft, _, _ in fail_details if 3 <= ft <= 10)
        late = sum(1 for _, ft, _, _ in fail_details if ft > 10)
        print(f"  Turn 0:     {t0_fails:3d}  (first-turn rotation / BOOST)")
        print(f"  Turn 1:     {t1_fails:3d}")
        print(f"  Turn 2:     {t2_fails:3d}")
        print(f"  Turn 3-10:  {early:3d}")
        print(f"  Turn 10+:   {late:3d}")

        # Failure type breakdown
        pos_errs = sum(1 for _, _, _, errs in fail_details if any("pos" in e for e in errs))
        ang_errs = sum(1 for _, _, _, errs in fail_details if any("angle" in e for e in errs))
        vel_errs = sum(1 for _, _, _, errs in fail_details if any("vel" in e for e in errs))
        cp_errs = sum(1 for _, _, _, errs in fail_details if any("next_cp" in e for e in errs))
        to_errs = sum(1 for _, _, _, errs in fail_details if any("timeout" in e for e in errs))
        print(f"\nError types (first error per battle):")
        print(f"  Position:   {pos_errs}")
        print(f"  Angle:      {ang_errs}")
        print(f"  Velocity:   {vel_errs}")
        print(f"  Checkpoint: {cp_errs}")
        print(f"  Timeout:    {to_errs}")

        sys.exit(1)
    else:
        print(f"\n*** ALL {passed} TESTED BATTLES PASSED — PHYSICS 100% ACCURATE ***")
        sys.exit(0)


if __name__ == "__main__":
    main()
