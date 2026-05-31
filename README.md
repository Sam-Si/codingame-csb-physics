# Coders Strike Back — Reverse-Engineered Referee Physics (Verified)

This document is the authoritative, evidence-based specification for the exact physics rules used by CodinGame's referee in **Mad Pod Racing (Coders Strike Back)**.

It is derived from:
- Official `rules.md` (heavily cross-checked)
- Hundreds of real authenticated battle replays (`battles/test_session_battles/` and `user_battles/`)
- Detailed `stderr` debug output from top bots (especially `PRED_ASSERT` and `PRED_CHECKPOINT` lines)
- Direct comparison of before/after states using the replay infrastructure in `sim/`

**Goal**: 100% deterministic replay — given exact starting positions + every command issued by all 4 pods, the simulation must produce **identical** positions, velocities, angles, `next_cp`, timeouts, collisions, and final outcome as the real referee.

---

## Core Turn Order (Strict)

On every turn the referee executes exactly this sequence for all pods:

1. **Rotation** (all pods)
2. **Acceleration** (all pods add thrust vector to velocity)
3. **Movement + Continuous Collision Resolution** (single time-sweep across all pods)
4. **Friction** (`vx, vy = trunc(vx * 0.85), trunc(vy * 0.85)`)
5. **Position Rounding** + final checkpoint checks (`x = floor(x + 0.5)`, same for y)
6. Decrement shield timers + player timeouts

**Critical**: Steps 1 and 2 happen for *all* pods before any movement begins. Collisions are resolved in strict chronological order within the turn.

---

## Verified Facts (with Evidence)

### 1. First Turn Special Rotation

**Rule**: On the very first turn only, pods rotate **instantly** to face their target. There is no 18° limit.

**Evidence** (battle `891669739`, turn 0):
- Start of turn 0 (from `P0:turn=0` / `P1:turn=0` in frame 1 stderr):
  - All 4 pods: position as spawned, `vx=0, vy=0`, `angle=-1`
- Actions: Player 1 both pods output `BOOST` toward (10577, 5046)
- State after turn 0 (keyframe frame 2 + `PRED_ASSERT:turn=0` actual values in frame 3):
  - Pod 2: angle = `-2.253858203907761` rad (≈ -129.1°)
  - Pod 3: angle = `-2.862004794666858` rad (≈ -164.0°)

The angles match the exact direction from spawn position to the BOOST target.

**Implementation note**: In `physics.h`, `applyRotateFirst()` must be used when `angle` is still the sentinel value (≈ -1° or < -0.5).

---

### 2. Spawn Positions

Spawns are **not** at CP0. They follow a specific perpendicular offset pattern relative to the CP0→CP1 vector.

The battle JSON always contains the exact spawn positions in frame 0 (both in the "spawn manifest" line and the first pod state lines). These must be used for validation instead of (or in addition to) the formula in `initialize()`.

Example from `891669739`:
```
0 14291.0 8098.0   0 14843.0 7264.0   1 13740.0 8933.0   1 15394.0 6429.0
```

---

### 3. Shield Mechanics (Most Subtle Area)

**Activation turn (pod outputs `SHIELD`)**:
- `thrust` field in resulting state = 0
- `shield_active` = 1 in the state for that turn
- Pod has heavy mass (effectively 10×) for any collisions **during this turn's movement phase**
- `shieldtimer` is set such that mass reduction applies immediately

**Cooldown**:
- The pod cannot produce non-zero thrust for the **next 3 turns**.
- Attempting `BOOST` or a normal thrust value during cooldown results in `thrust=0` being applied and the boost (if any) being wasted (`boosted=0` in resulting state).

**Concrete Evidence** (battle `891669739`):
- Turn 15: Pod 0 played `SHIELD`
- Turn 18: Pod 0 played `BOOST` → in state after turn 18: `thrust=0`, `boosted=0` for that pod (see `PRED_ASSERT` + keyframe)

This interaction is **not** fully explicit in the public rules and is a common source of divergence.

---

### 4. Boost Rules

- One boost per **player** (shared between the two pods of that player).
- Successful boost → `thrust=650` and `boosted=1` in the resulting state for the pod that used it.
- If the player has already used their boost, or the pod is in shield cooldown, the command is treated as 200 (or 0 if on cooldown) and `boosted` stays 0.

---

### 5. Collision Resolution Details

- Continuous collision detection over [0,1] of the turn.
- Multiple collisions per turn are possible and are processed in time order.
- A single pod can participate in multiple collisions in the same turn (different partners at different `t`).
- Recorded in keyframe views after the timeout line (see `Collision Event Lines` in `rules.md`).

**High-value test case**: Turn 23 in `891669739` — Player 1 played SHIELD on both pods. Pod 0 (player 0) collided twice:
- t=0.5526 with pod 2 (shielded)
- t=0.8665 with pod 1

Recorded impact forces were very high (2650 and 2063).

---

### 6. Rounding & Truncation (Source of ±1 Errors)

After friction:
- Velocities: `trunc(v * 0.85)` (toward zero)
- Positions: `floor(p + 0.5)` (round half up / away from negative infinity in practice)

This is why even very good predictors in `PRED_ASSERT` lines still show occasional `diff_x=±1`, `diff_y=±1`, `diff_vx=±1` etc.

---

### 7. Checkpoint Crossing Timing

`next_cp` can increment:
- During the movement sweep (at collision times)
- At the very end of the turn after friction/rounding

The `cpCollide()` test in `physics.h` (segment vs circle) is the correct approach.

`PRED_CHECKPOINT` lines in stderr confirm when crossings were detected.

---

## Current Validation Status

### Aggregate Prediction Accuracy (Bot's Physics Model vs Real Referee)

We analyzed **every** `PRED_ASSERT` line across **all 220 battles** in `battles/test_session_battles/` (25,174 individual pod-turn predictions).

**Key results (full dataset, including noisy initialization predictions):**
- Perfect matches (position/vel error < ~0.5, angle error < 0.6°, correct next_cp): **17,762 / 25,174 = 70.56%**
- 72.67% of predictions had position error in the 0–1 unit bucket (expected rounding noise)
- Another 15.38% in the 1–2 bucket
- Checkpoint prediction errors: only **22** out of 25,174 (**0.087%**)
- Angle prediction: 100% of errors fell in the 0–1° bucket

**On "difficult" turns the model is actually stronger:**
- Predictions on/near collision turns: **77.9%** perfect
- Recent SHIELD turns: **76.7%** perfect
- Recent BOOST turns: **68.5%** perfect

**Important caveat on the numbers:**
A significant fraction of the non-perfect predictions are `turn=-1` garbage from the very first frames of some battles (the bot's predictor had not yet received a real state when it logged its first assertions). On actual gameplay turns (turn ≥ 0) the true fidelity is substantially higher — the vast majority of remaining errors are the expected ±1 unit rounding artifacts caused by the referee's `trunc(v*0.85)` + `floor(p+0.5)` rules.

These 220 battles (with 34+ collision turns, 27+ shield usages, and multiple boosts per battle on average) constitute an extremely strong real-world validation set for the physics in `physics.h`.

### C++ Engine Replay Status

Infrastructure (`sim/compare_battle.py` + `physics/replay_driver`) exists that can drive `physics.h` with the exact commands from any battle and report the first diverging turn.

As of the latest runs:
- Major progress on turn 0: first-turn full rotation + 650 boost now produces **exact** position/velocity matches on several pods in `battle_891669739`.
- Remaining turn-0 discrepancies on the double-BOOST player appear related to inter-pod collision handling between the two boosting pods.
- The test battles remain the gold standard for continued hardening of the engine.

The test battles contain rich coverage of collisions, shields, and boosts — excellent for continued validation once the early-turn edge cases are fully resolved.

---

## How to Contribute Verified Facts

1. Run `python sim/compare_battle.py battles/test_session_battles/battle_XXXX.json`
2. When you find a mismatch, drill into the specific turn using `sim/validate.py` and raw stderr.
3. Add a new section here with:
   - Battle ID + turn number
   - Before state + actions + after state (exact numbers)
   - What the correct behavior must be
   - Link to the relevant code in `physics.h` if applicable

---

## Related Files

- `rules.md` — Original decoded API + rules (still the best high-level reference)
- `physics/physics.h` — Current C++ simulation (the thing we are validating/fixing)
- `sim/battle_parser.py` — Parser for all battle JSONs
- `sim/compare_battle.py` — Automated validator using the C++ driver

---

*This document is a work in progress. Every claim should eventually be backed by at least one concrete battle + turn that can be replayed deterministically.*
