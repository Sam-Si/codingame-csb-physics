#!/usr/bin/env python3
"""
Full battle replay validator using your C++ physics engine.

Runs an entire test_session_battle (or any battle JSON) through the
compiled physics/replay_driver and compares every post-turn state
against the ground truth recorded by the real referee.

Usage:
    python sim/compare_battle.py battles/test_session_battles/battle_891669739.json [--max-turns 20]

It will stop at the first significant divergence and print a detailed report.
This is the tool you can use to gain high confidence that your physics
produces the correct final outcome given start + all moves.
"""

from __future__ import annotations
import sys
import math
from battle_parser import load_battle
from physics_driver import CppPhysics


def pos_close(a: float, b: float, tol: float = 1.0) -> bool:
    return abs(a - b) <= tol

def vel_close(a: int, b: int, tol: int = 1) -> bool:
    return abs(a - b) <= tol

def angle_close(a: float, b: float, tol_deg: float = 1.0) -> bool:
    da = abs(a - b)
    da = min(da, 2*math.pi - da)
    return da <= (tol_deg * math.pi / 180.0)

def _is_invalid_thrust(thrust_str):
    if thrust_str in ("SHIELD", "BOOST"):
        return False
    try:
        val = int(thrust_str)
        return val < 0 or val > 200
    except (ValueError, TypeError):
        return False


def compare_one_turn(turn: int, sim_pods: list, gt_pods: list,
                     sim_timeouts, gt_timeouts, n_checkpoints=0) -> list[str]:
    """Return list of mismatch descriptions, or [] if perfect match."""
    errs = []
    for i in range(4):
        sp = sim_pods[i]
        gp = gt_pods[i]

        if not (pos_close(sp["x"], gp.x) and pos_close(sp["y"], gp.y)):
            errs.append(f"pod{i} pos: sim=({sp['x']:.1f},{sp['y']:.1f}) gt=({gp.x:.1f},{gp.y:.1f})")

        if not (vel_close(sp["vx"], gp.vx) and vel_close(sp["vy"], gp.vy)):
            errs.append(f"pod{i} vel: sim=({sp['vx']},{sp['vy']}) gt=({gp.vx},{gp.vy})")

        if not angle_close(sp["angle"], gp.angle or 0.0, tol_deg=1.0):
            errs.append(f"pod{i} angle: sim={math.degrees(sp['angle']):.1f}° gt={math.degrees(gp.angle or 0):.1f}°")

        sim_cp = sp["next"] % n_checkpoints if n_checkpoints > 0 else sp["next"]
        if sim_cp != gp.next_cp:
            errs.append(f"pod{i} next_cp: sim={sp['next']}(mod={sim_cp}) gt={gp.next_cp}")

    if sim_timeouts != gt_timeouts:
        errs.append(f"timeouts: sim={sim_timeouts} gt={gt_timeouts}")

    return errs


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    max_turns = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 999999

    log = load_battle(path)
    print(f"Validating {path}")
    print(f"  {len(log.turns)} turns, {len(log.checkpoints)} checkpoints")
    print(f"  Final referee outcome: ranks={log.ranks}, timeouts p0/p1 = {log.keyframes[-1].timeout_p0}/{log.keyframes[-1].timeout_p1}")

    phys = CppPhysics()
    phys.init_battle(log.checkpoints, laps=log.laps)

    # Inject *exact* initial state from the battle (critical)
    init = log.initial_state
    for i, p in enumerate(init.pods):
        ang = p.angle if p.angle is not None else -0.0174533
        phys.set_pod(i, p.x, p.y, p.vx, p.vy, ang, p.next_cp, p.shield_active, p.boosted)
    phys.set_timeouts(init.timeout_p0, init.timeout_p1)

    first_mismatch = None
    for t, ta in enumerate(log.turns):
        if t >= max_turns:
            break

        # InvalidInput propagation (same logic as verify_battles.py)
        p0_acts = [(ta.p0_pod0.target_x, ta.p0_pod0.target_y, ta.p0_pod0.thrust),
                   (ta.p0_pod1.target_x, ta.p0_pod1.target_y, ta.p0_pod1.thrust)]
        p1_acts = [(ta.p1_pod0.target_x, ta.p1_pod0.target_y, ta.p1_pod0.thrust),
                   (ta.p1_pod1.target_x, ta.p1_pod1.target_y, ta.p1_pod1.thrust)]

        if _is_invalid_thrust(p0_acts[0][2]):
            inv = p0_acts[0][2]
            p0_acts = [(p0_acts[0][0], p0_acts[0][1], inv),
                       (p0_acts[1][0], p0_acts[1][1], inv)]
        elif _is_invalid_thrust(p0_acts[1][2]):
            pass  # only second pod invalidated

        if _is_invalid_thrust(p1_acts[0][2]):
            inv = p1_acts[0][2]
            p1_acts = [(p1_acts[0][0], p1_acts[0][1], inv),
                       (p1_acts[1][0], p1_acts[1][1], inv)]
        elif _is_invalid_thrust(p1_acts[1][2]):
            pass  # only second pod invalidated

        phys.apply(0, p0_acts[0][0], p0_acts[0][1], p0_acts[0][2])
        phys.apply(1, p0_acts[1][0], p0_acts[1][1], p0_acts[1][2])
        phys.apply(2, p1_acts[0][0], p1_acts[0][1], p1_acts[0][2])
        phys.apply(3, p1_acts[1][0], p1_acts[1][1], p1_acts[1][2])

        sim = phys.step()
        gt = log.keyframes[t]

        errs = compare_one_turn(t, sim["pods"], gt.pods, sim["timeouts"],
                                (gt.timeout_p0, gt.timeout_p1),
                                n_checkpoints=len(log.checkpoints))

        if errs:
            if first_mismatch is None:
                first_mismatch = t
            print(f"\n!!! MISMATCH after turn {t}")
            for e in errs:
                print("   ", e)
            print("   (stopping at first divergence)")
            break

        if t % 20 == 0:
            print(f"  turn {t:3d} OK (timeouts {sim['timeouts']})")

    if first_mismatch is None:
        print(f"\n=== PERFECT MATCH through all {len(log.turns)} turns ===")
        print("Your physics engine produces identical states to the referee on this battle.")
    else:
        print(f"\nFirst divergence at turn {first_mismatch}")
        print("Use this + the collision/shield/boost turns reported by validate.py to debug physics.h")

    phys.close()


if __name__ == "__main__":
    main()
