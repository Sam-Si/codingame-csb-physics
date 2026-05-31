# Coders Strike Back — Game Rules & Raw API Format

## Game Rules

### Goal
Win the race.

### Rules
The players each control a team of two pods during a race. As soon as a pod completes the race, that pod's team is declared the winner.
The circuit of the race is made up of checkpoints. To complete one lap, your vehicle (pod) must pass through each one in order and back through the start. The first player to reach the start on the final lap wins.

The game is played on a map 16000 units wide and 9000 units high. The coordinate X=0, Y=0 is the top left pixel.

The checkpoints work as follows:
- The checkpoints are circular, with a radius of 600 units.
- Checkpoints are numbered from 0 to N where 0 is the start and N-1 is the last checkpoint.
- The disposition of the checkpoints is selected randomly for each race.

The pods work as follows:
- To pass a checkpoint, the center of a pod must be inside the radius of the checkpoint.
- To move a pod, you must print a target destination point followed by a thrust value.
- The thrust value of a pod is its acceleration and must be between 0 and 200.
- The pod will pivot to face the destination point by a maximum of 18 degrees per turn and will then accelerate in that direction.
- You can use 1 acceleration boost in the race, you only need to replace the thrust value by the BOOST keyword.
- You may activate a pod's shields with the SHIELD command instead of accelerating. This will give the pod much more weight if it collides with another. However, the pod will not be able to accelerate for the next 3 turns.
- The pods have a circular force-field around their center, with a radius of 400 units, which activates in case of collisions with other pods.
- The pods may move normally outside the game area.
- If none of your pods make it to their next checkpoint in under 100 turns, you are eliminated and lose the game. Only one pod need to complete the race.

### Victory Conditions
Be the first to complete all the laps of the circuit with one pod.

### Lose Conditions
- Your program provides incorrect output.
- Your program times out.
- None of your pods reach their next checkpoint in time.
- Somebody else wins.

### Expert Rules
On each turn the pods movements are computed this way:
1. **Rotation:** the pod rotates to face the target point, with a maximum of 18 degrees (except for the 1st round).
2. **Acceleration:** the pod's facing vector is multiplied by the given thrust value. The result is added to the current speed vector.
3. **Movement:** The speed vector is added to the position of the pod. If a collision would occur at this point, the pods rebound off each other.
4. **Friction:** the current speed vector of each pod is multiplied by 0.85
5. The speed's values are truncated and the position's values are rounded to the nearest integer.

- Collisions are elastic. The minimum impulse of a collision is 120.
- A boost is in fact an acceleration of 650. The number of boost available is common between pods. If no boost is available, the maximum thrust is used.
- A shield multiplies the Pod mass by 10.
- The provided angle is absolute. 0° means facing EAST while 90° means facing SOUTH.

### Game Input

**Initialization input:**
- Line 1: `laps` — the number of laps to complete the race.
- Line 2: `checkpointCount` — the number of checkpoints in the circuit.
- Next `checkpointCount` lines: 2 integers `checkpointX`, `checkpointY` for the coordinates of each checkpoint.

**Input for one game turn:**
- First 2 lines: Your two pods.
- Next 2 lines: The opponent's pods.
- Each pod is represented by: 6 integers — `x` & `y` for the position, `vx` & `vy` for the speed vector, `angle` for the rotation angle in degrees, `nextCheckPointId` for the number of the next checkpoint the pod must go through.

**Output for one game turn:**
- Two lines: 2 integers for the target coordinates of your pod followed by `thrust`, the acceleration to give your pod, or by `SHIELD` to activate the shields, or by `BOOST` for an acceleration burst. One line per pod.

**Constraints:**
- 0 ≤ thrust ≤ 200
- 2 ≤ checkpointCount ≤ 8
- Response time first turn ≤ 1000ms
- Response time per turn ≤ 75ms

---

# Raw API Response Format (Fully Decoded)

Verified against game `891665074` using `findInformationById` with stderr debug output from the player bot.

---

## API Endpoints

### `POST /services/gameResult/findByGameId`
**Payload:** `[gameId, viewerUserId]` (use `null` for anonymous)
**Returns:** The `gameResult` object directly.

### `POST /services/gameResult/findInformationById`
**Payload:** `["gameId", viewerUserId]` (gameId as **string**)
**Returns:** A wrapper with the `gameResult` nested inside, plus viewer JS, puzzle metadata, etc.

```json
{
  "puzzleTitle": ["Mad Pod Racing", "fr title"],
  "puzzleId": 148,
  "gameResult": { /* same structure as findByGameId response */ },
  "viewer": "function unlerpUnclamped(...) { ... }",
  "shareable": true,
  "questionTitle": "Mad Pod Racing"
}
```

**Key difference:** `findInformationById` returns `stderr` in frames (your `cerr` output) because you are the authenticated viewer. `findByGameId` with `null` viewer does NOT include `stderr`.

---

## `gameResult` Top-Level Structure

```json
{
  "frames":        [],     // Array of frame objects (the core game replay data)
  "gameId":        int,    // e.g. 891665074
  "refereeInput":  string, // Newline-delimited key=value pairs
  "scores":        [float, float],  // Final scores (higher = winner)
  "ranks":         [int, int],      // 0-indexed rank (0=winner, 1=loser)
  "tooltips":      [string],        // JSON-encoded event messages
  "agents":        [agent, agent]   // Player/bot metadata
}
```

### `refereeInput` (parsed)

```
seed=920111793
pod_timeout=100
map=13125 2291 4566 2182 7366 4941 3316 7224 14588 7689 10556 5071
pod_per_player=2
```

| Field | Description |
|---|---|
| `seed` | Random seed for map generation |
| `pod_timeout` | Turns before elimination if no checkpoint reached (always 100) |
| `map` | Flat list of checkpoint x,y pairs |
| `pod_per_player` | Pods per player (always 2) |

**Laps is NOT in `refereeInput`.** It's hardcoded to **3** by the referee for Legend league. Your bot receives it as the first line of initialization input.

### `agents`

```json
{
  "index": 0,
  "codingamer": {
    "userId": 984614,
    "pseudo": "SamSi",
    "avatar": 9557317848695
  },
  "agentId": -1    // -1/-2 for IDE tests, positive for ranked bots
}
```

### `tooltips`

JSON-encoded strings with game events:
```json
"{\"turn\":416,\"text\":\"$0 did not reach the next checkpoint in time\",\"event\":0}"
```

---

## Frame Structure

Each frame is one "step" in the replay. Frames alternate between players.

```json
{
  "gameInformation": string,  // Human-readable action description
  "summary":         string,  // Rank summary (only on keyframes)
  "view":            string,  // The core game state data (parsed below)
  "keyframe":        bool,    // true = full state; false = just a marker
  "agentId":         int,     // -1 = init, 0 = player 0's move, 1 = player 1's move
  "stdout":          string,  // Player's raw output (only on player frames)
  "stderr":          string   // Player's cerr output (only if you're the authenticated viewer)
}
```

### Frame Ordering Pattern

| Frame Index | agentId | keyframe | Description |
|---|---|---|---|
| 0 | -1 | **true** | Initial state (full view with headers) |
| 1 | 0 | false | Player 0's first move (stdout only) |
| 2 | 1 | **true** | Player 1's first move + full state after turn 1 |
| 3 | 0 | false | Player 0's second move |
| 4 | 1 | **true** | Player 1's second move + full state after turn 2 |
| ... | alternating | ... | Pattern continues |

**Keyframes** (even-indexed after 0) contain the full game state in `view`. Non-keyframes just have the frame number. The game turn number = frame_index / 2.

---

## View String Format

### Frame 0 — Initial Keyframe

```
 0                                                          ← frame number
CodersStrikeBack                                            ← game engine name
16000 9000 400 600 4 0.3141592653589793                     ← constants line
13125 2291 4566 2182 7366 4941 3316 7224 14588 7689 ...     ← checkpoint coordinates
0 13119.0 2791.0 0 13131.0 1791.0 1 13106.0 3791.0 ...     ← spawn manifest
13119.0 2791.0 0 0 0 0 null null null 0 1 1                 ← pod 0 state
""                                                          ← pod 0 message (empty)
13131.0 1791.0 0 0 0 0 null null null 0 1 1                 ← pod 1 state
""                                                          ← pod 1 message
13106.0 3791.0 0 0 0 0 null null null 0 1 1                 ← pod 2 state
""                                                          ← pod 2 message
13144.0 791.0 0 0 0 0 null null null 0 1 1                  ← pod 3 state
""                                                          ← pod 3 message
1:100 1:100                                                 ← timeout counters
```

#### Constants Line

```
16000 9000 400 600 4 0.3141592653589793
  │     │    │   │  │  └── max rotation per turn (radians) = 18° = π/10
  │     │    │   │  └───── total pod count (always 4 = 2 players × 2 pods)
  │     │    │   └──────── checkpoint activation radius (600 units)
  │     │    └───────────── pod hitbox radius (400 units, diameter=800 for collision)
  │     └────────────────── field height (9000)
  └──────────────────────── field width (16000)
```

**The `4` in the constants line is the total pod count, NOT the checkpoint count and NOT the lap count.**

#### Checkpoint Line

Flat pairs of `x y` for each checkpoint, in order:
```
13125 2291 4566 2182 7366 4941 3316 7224 14588 7689 10556 5071
  CP0        CP1        CP2        CP3        CP4        CP5
```

Number of checkpoints = (number of values) / 2. Can be 2–8.

#### Spawn Manifest

```
0 13119.0 2791.0  0 13131.0 1791.0  1 13106.0 3791.0  1 13144.0 791.0
│   x       y     │   x       y     │   x       y     │   x       y
└ player0 pod0    └ player0 pod1    └ player1 pod0    └ player1 pod1
```

Format: repeating triplets of `owner_player_id x y`

### Pod State Line (12 fields)

```
13118.0 2980.0 17 -18 200 0 13106 3791 1.583795594535813 0 1 2
```

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | `x` | float | X position |
| 1 | `y` | float | Y position |
| 2 | `vx` | int | X velocity |
| 3 | `vy` | int | Y velocity |
| 4 | `thrust` | int | Applied thrust this turn (0 during shield cooldown, 650 for BOOST) |
| 5 | `shield_active` | int | 1 = shield was just activated on this turn (pod eliminated: also 1) |
| 6 | `target_x` | int/null | Target X from player output (`null` at frame 0) |
| 7 | `target_y` | int/null | Target Y from player output (`null` at frame 0) |
| 8 | `angle` | float/null | Facing angle in **radians** (`null` at frame 0 = not yet set). 0 = East, positive = clockwise |
| 9 | `boosted` | int | 1 = this pod used its BOOST on this turn |
| 10 | `next_cp` | int | Next checkpoint index to reach (wraps cyclically: 0→1→2→...→N-1→0→1→...) |
| 11 | `z_order` | int | Visual display/z-ordering for the viewer (changes each frame) |

**Angle conversion:** `degrees = angle_rad × 180/π`. The game rounds to nearest integer for player input.

At frame 0, fields 6–8 are `null` because no commands have been issued yet.

#### Pod Message Line

After each pod state line, a quoted string with the player's raw `stdout` for that pod:
- `""` — no output / initial frame
- `"650 -4 BOOST"` — player's raw output echoed

### Subsequent Keyframes (Frame 2, 4, 6, ...)

```
 2                                                          ← frame number
13118.0 2980.0 17 -18 200 0 13106 3791 1.5837... 0 1 2     ← pod 0 state
""                                                          ← pod 0 message
2732.0 5595.0 111 128 200 0 68248 81143 0.8563... 0 1 1    ← pod 1 state
""                                                          ← pod 1 message  
4016.0 4103.0 45 72 100 0 6299 7744 1.0107... 0 1 3        ← pod 2 state
""                                                          ← pod 2 message
2212.0 6415.0 80 26 100 0 6299 7744 0.3144... 0 1 4        ← pod 3 state
""                                                          ← pod 3 message
1:99 2:99                                                   ← timeout counters
0 0.952 3 13069 803 1 13133 1601 222.749 -38 -94            ← collision event(s)
2 0.952 2 13031 3777 0 13117 2981 222.727 -41 93            ← collision event(s)
```

#### Timeout Counters

```
1:99 2:99
 │ │   │ │
 │ │   │ └── player 1 remaining turns before timeout
 │ │   └──── player 1's checkpoint progress factor
 │ └──────── player 0 remaining turns before timeout
 └────────── player 0's checkpoint progress factor
```

Format: `p0_progress:p0_timeout p1_progress:p1_timeout`

- Starts at `1:100 1:100`
- Timeout decrements each turn. Resets to 100 when ANY pod of that player reaches a checkpoint.
- When it reaches `-1`, the player is eliminated (`"$0 did not reach the next checkpoint in time"`).

#### Non-Keyframes (Odd frames)

```
 3
```

Just the frame number on one line. The actual player output is in `stdout`.

---

## Collision Event Lines

Appear after the timeout counters in keyframes where collisions occurred.

```
0 0.9522041132903492 3 13069 803 1 13133 1601 222.7492148004719 -38 -94
```

| Index | Field | Type | Description |
|---|---|---|---|
| 0 | `collision_id` | int | Global running collision counter across the entire game |
| 1 | `t` | float | Collision time within the turn (0.0 = start, 1.0 = end) |
| 2 | `pod_a` | int | First pod index (0–3) |
| 3 | `pod_a_x` | int | Pod A x-position at moment of collision |
| 4 | `pod_a_y` | int | Pod A y-position at moment of collision |
| 5 | `pod_b` | int | Second pod index (0–3) |
| 6 | `pod_b_x` | int | Pod B x-position at moment of collision |
| 7 | `pod_b_y` | int | Pod B y-position at moment of collision |
| 8 | `impact_force` | float | Force/impulse magnitude of the collision |
| 9 | `impulse_x` | int | X component of the collision impulse |
| 10 | `impulse_y` | int | Y component of the collision impulse |

Multiple collisions can occur per turn (multiple lines). The distance between `pod_a` and `pod_b` at collision is always ≈800 (2 × pod radius).

---

## End-of-Game View

The final keyframe's `view` line 0 has the format:
```
656 endReached
```

And the `summary` says:
```
$0 eliminated! rank: 2
$1 rank: 1
```

---

## Mapping: Raw API → Game Input (What Bots Receive)

### Initialization Input

| Bot reads | Source |
|---|---|
| `laps` | **Hardcoded 3** (not in API data) |
| `checkpoint_count` | Count pairs in `refereeInput.map` or view line 3 |
| `checkpoint_x checkpoint_y` (× N) | View line 3 or `refereeInput.map` |

### Per-Turn Input (for each of your 2 pods)

| Bot reads | View field |
|---|---|
| `x` | `p[0]` (truncated to int) |
| `y` | `p[1]` (truncated to int) |
| `vx` | `p[2]` |
| `vy` | `p[3]` |
| `angle` | `round(degrees(p[8]))`, normalized 0–359. -1 on first turn |
| `nextCheckPointId` | `p[10]` |

### Per-Turn Input (for each of opponent's 2 pods)

Same fields, from pod indices 2 and 3.

### Bot Output

```
target_x target_y thrust_or_SHIELD_or_BOOST
target_x target_y thrust_or_SHIELD_or_BOOST
```

This appears in `frames[N].stdout`. Also echoed in the pod message line (quoted string after pod state).

---

## Pod Index Mapping

| Pod Index | Owner | Role |
|---|---|---|
| 0 | Player 0 (`$0`) | Pod 1 |
| 1 | Player 0 (`$0`) | Pod 2 |
| 2 | Player 1 (`$1`) | Pod 1 |
| 3 | Player 1 (`$1`) | Pod 2 |

---

## stderr Format (Debug Output)

Only visible when you're the authenticated viewer calling `findInformationById`.

```
INIT:laps=3;checkpoint_count=6;cp0_x=13125;cp0_y=2291;...

P0:turn=0;id=0;x=13119;y=2791;vx=0;vy=0;angle=-1;target_cp=1;action=200;target_x=13106;target_y=3791;opp_id=2;opp_x=13106;opp_y=3791;opp_vx=0;opp_vy=0;opp_angle=-1;opp_target_cp=1
P1:turn=0;id=1;x=13131;y=1791;vx=0;vy=0;angle=-1;target_cp=1;action=200;target_x=13144;target_y=791;opp_id=3;opp_x=13144;opp_y=791;opp_vx=0;opp_vy=0;opp_angle=-1;opp_target_cp=1
```

This confirms:
- **laps = 3** (not stored in API, hardcoded by referee)
- **angle = -1** on first turn (maps to `null` in view)
- **next_checkpoint starts at 1** (CP 0 is where you spawn; first target is CP 1)
- **opponent pods are indices 2 and 3**