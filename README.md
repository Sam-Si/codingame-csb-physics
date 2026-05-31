# Coders Strike Back — Verified Referee Physics Engine

**Status: 100% accurate** — `physics/physics.h` reproduces every turn of every playable battle identically to the CodinGame referee.

```
$ python sim/verify_battles.py battles/test_session_battles
  209/209 tested battles PASSED (24,546 turns, 100.00% accuracy)
  11 skipped (first-turn timeouts — no actions to simulate)
```

---

## Verification Methodology

Given a battle JSON from CodinGame:
1. Parse exact initial state (positions, velocities, angles) from frame 0
2. Parse exact player commands (target_x, target_y, thrust) from every frame's `stdout`
3. Parse ground-truth post-turn state from every keyframe's `view` data
4. Feed initial state + exact commands into `physics.h` via `physics/replay_driver`
5. Compare engine output vs referee state **every single turn** — position, velocity, angle, next_cp, timeouts

A battle PASSes only if **every turn** matches within rounding tolerance (pos ±1, vel ±1, angle ±1°).

---

## Frame / Turn Mapping

```
game_turn = (frame_index - 1) // 2

Frame 0             → init state (keyframe=true, NOT a game turn)
Frame 2T+1          → Player 0 submits actions for turn T (keyframe=false)
Frame 2T+2          → Player 1 submits actions for turn T (keyframe=true, state AFTER turn T)
```

Frames with `keyframe=true` contain the actual game state in the `view` field.
Frame 0 is the initialization frame (spawn positions, checkpoints).

---

## Core Turn Loop (5 Steps, Order Critical)

On every turn the referee executes exactly:

1. **Rotation** — each pod rotates toward its target (max 18°/turn, except turn 0)
2. **Acceleration** — thrust vector added to velocity along facing direction
3. **Movement + Collisions** — continuous-time sweep over `[0, 1.0]`, resolve all pod-pod collisions in chronological order, check checkpoint crossings between collisions
4. **Friction + Rounding** — `v = trunc(v * 0.85)`, `p = floor(p + 0.5)`
5. **Timers** — decrement shield cooldowns, decrement player timeouts

Steps 1-2 happen for **all 4 pods** before any movement begins.

---

## Verified Rules (All Proven Against 209+ Real Battles)

### 1. First-Turn Rotation (Turn 0)

No 18° rotation limit. The pod faces directly toward the target:
```
angle = atan2(target_y - pod_y, target_x - pod_x)
```

The referee uses `atan2` which returns values in `[-π, π]`. Our engine normalizes to this range (not `[0, 2π]`).

**Evidence**: All 209 battles pass turn 0 with this rule. The original bot code used `[0, 2π]` normalization which was a known bug.

### 2. Normal Rotation (Turn 1+)

Clamped to ±18° per turn:
```cpp
double rotateAngle = diffAngle(target);  // shortest arc in [-π, π]
if (rotateAngle < -maxRotate) angle = angle - maxRotate;
else if (rotateAngle > maxRotate) angle = angle + maxRotate;
else angle = atan2(target_y - pod_y, target_x - pod_x);
```

### 3. Boost (Per-Pod, Not Per-Player)

Each of the 4 pods can BOOST **once per game independently**.

- Successful BOOST: thrust = 650, `boosted` flag set to 1
- Already boosted: treated as thrust = 200
- BOOST during shield cooldown: **not consumed** (boosted stays 0), thrust = 0

**Evidence**: Battles show both pods of the same player BOOSTing independently. The original bot tracked boost per-player — this was a bug.

### 4. Shield Mechanics

**Activation** (`SHIELD` command):
- `shieldtimer` set to 4
- Pod mass becomes 10× for collisions **this turn** (mass = 0.1 in inverse-mass formulation)
- Thrust = 0 (no acceleration)
- Rotation still applied normally

**Cooldown** (turns with `shieldtimer > 0`):
- No thrust applied regardless of command
- If BOOST requested during cooldown → boost NOT consumed, thrust = 0
- Timer decrements by 1 each turn at end-of-turn
- Total lockout: 4 turns (activation turn + 3 cooldown turns)

### 5. InvalidInput (Negative Thrust)

When a player's stdout contains a negative thrust value (e.g., `-1`):

**Per-pod behavior**: Shield activates, **no rotation**, no thrust (angle stays exactly unchanged, velocity is pure friction).

**Propagation rule** (verified from 4 battles with `thrust=-1`):
- If the **first line** (pod 0 of that player) is invalid → **both** pods invalidated
- If only the **second line** (pod 1) is invalid → only that pod invalidated

The referee reads stdout line-by-line; an error on line 1 prevents parsing line 2.

**Evidence**:
| Battle | Invalid line | Both pods affected? |
|--------|-------------|-------------------|
| 891670128 | P0 line 2 | No — only pod1 |
| 891670142 | P0 line 2 | No — only pod1 |
| 891670250 | P1 line 2 | No — only pod3 |
| 891670251 | P0 line 1 | Yes — pod0 AND pod1 |

### 6. Collision Physics

**Detection**: Continuous-time sweep. For each pod pair, solve the quadratic for when distance = 1600 (2× pod radius 800). Take the earliest collision time.

**Resolution**: Modified elastic collision with minimum impulse:
```cpp
force = normal.dot(relativeVelocity) / (invMass_a + invMass_b);
if (force < 120.0) force += 120.0;  // minimum impulse
else force += force;                 // double the force (elastic)
```

Shield mass: `invMass = 0.1` (10× heavier). Normal mass: `invMass = 1.0`.

**Overlap correction**: If pods are already overlapping (`distance ≤ 800`), push apart by `(800 - distance) / 2 + EPSILON` along the normal.

**Multiple collisions**: Resolved in strict time order. After each collision, re-sweep remaining time for new collisions.

### 7. Checkpoint Detection

Segment-vs-circle test: does the movement segment from `start_pos` to `end_pos` pass within 600 units of the next checkpoint?

Checkpoints are checked:
- Between collisions (during the movement sweep)
- At end of turn after friction/rounding

The engine uses a global linear checkpoint index: `laps × num_checkpoints + 1` total entries. The referee's `view` shows `next_cp % num_checkpoints`.

### 8. Timeout System

Each player starts with 100 timeout ticks. Decremented by 1 every turn.

When a pod passes its next checkpoint: player's timeout resets to 100 (set to 101, then decremented by 1 at end of turn = net 100).

If timeout reaches 0, the player is eliminated.

### 9. Rounding

- **Velocities**: `trunc(v * 0.85)` — toward zero (C `trunc()`)
- **Positions**: `floor(p + 0.5)` — round half-up (standard rounding)

These happen after friction and movement, before the next turn begins.

### 10. Spawn Positions

Pods spawn perpendicular to the CP0→CP1 vector with specific offsets:
```
startPointMult = [{500, -500}, {-500, 500}, {1500, -1500}, {-1500, 1500}]
unit = normalize(CP1 - CP0)
pod[i].x = floor(CP0.x + unit.y * mult[i].x + 0.5)
pod[i].y = floor(CP0.y + unit.x * mult[i].y + 0.5)
```

Pods 0,1 belong to Player 0. Pods 2,3 belong to Player 1.

---

## Bugs Found in the Original Bot Code

The bot source (used to generate `stderr` logs) had several physics bugs relative to the referee:

| Bug | Bot code | Correct (verified) |
|-----|---------|-------------------|
| Angle normalization | `[0, 2π]` in `applyRotateFirst` | `[-π, π]` (atan2 convention) |
| Boost tracking | Per-player | Per-pod (each pod has its own) |
| First-turn detection | `turn == 1` counter check | `isFirstTurn` flag per pod |
| Timeout reset | `playerTimeout = 100` | `playerTimeout = 101` (then -1 = net 100) |
| InvalidInput handling | Not handled | Shield + no rotation |

Despite these bugs, the bot's `PRED_ASSERT` accuracy was ~70% on perfect matches (position within ±1, angle within ±1°). The remaining 30% were primarily rounding artifacts, first-frame noise, and the bugs above.

---

## Quick Start

### Verify all battles
```bash
python sim/verify_battles.py battles/test_session_battles
```

### Debug a single battle
```bash
python sim/compare_battle.py battles/test_session_battles/battle_891669739.json
```

### Rebuild the C++ driver
```bash
g++ -std=c++17 -O2 -o physics/replay_driver physics/replay_driver.cpp
```

---

## File Reference

| File | Purpose |
|------|---------|
| `physics/physics.h` | **The verified physics engine** — 100% referee-accurate |
| `physics/replay_driver.cpp` | C++ text-protocol driver for physics.h |
| `sim/battle_parser.py` | Parses battle JSON → structured data |
| `sim/physics_driver.py` | Python subprocess wrapper for C++ driver |
| `sim/verify_battles.py` | Batch verifier (the definitive test) |
| `sim/compare_battle.py` | Single-battle debugger with detailed output |
| `rules.md` | Original game rules reference |
| `battles/test_session_battles/` | 220 real battle replays (test corpus) |
