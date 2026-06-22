# Leaderboard Battles — Categorized

**Filter:** only battles strictly after `battle_870230019.json` (id > 870230019).
**Total:** 17011

Only non-empty category folders are kept (empty outcome classes omitted from disk).

## Timeout labels

| Label | Count | Where |
|-------|------:|-------|
| timeout_yes | 1604 | primary elim folders + `18_timeout_yes_any/` |
| timeout_no | 15407 | all other primaries |
| clean finish (subset of no-timeout) | 15368 | `19_timeout_no_clean_finish/` |

Timeout types in `manifest.csv` → `timeout_type` column:
- `agent_program` — bot failed to print output in time
- `pod_checkpoint` — in-game 100-turn checkpoint timer reached 0 (player eliminated)
- `none` — no timeout

Agent program timeouts are usually pre-segregated in `battles/leaderboard_timeouts/`.

## Primary categories present (mutually exclusive, priority order)

| # | Folder | Count | Description |
|--:|--------|------:|-------------|
| 1 | `02_invalid_input_abort/` | 9 | Invalid input abort — illegal thrust/power. |
| 2 | `03_double_elimination/` | 1 | Both players eliminated. |
| 3 | `04_max_rounds_stalemate/` | 32 | Turn/frame limit hit, no race finish. |
| 4 | `05_end_reached_with_elimination/` | 7 | Finish + elimination edge case. |
| 5 | `06_end_reached_marathon/` | 2139 | Finish with 300+ game turns. |
| 6 | `07_end_reached_sprint/` | 103 | Finish in under 80 turns. |
| 7 | `08_end_reached_collision_fest/` | 586 | Finish with >80 collisions. |
| 8 | `09_end_reached_shield_heavy/` | 8289 | Finish with 20+ SHIELD uses. |
| 9 | `10_end_reached_boost_heavy/` | 1332 | Finish with 4+ BOOST uses. |
| 10 | `11_end_reached_standard/` | 2919 | Baseline clean finishes. |
| 11 | `13_elim_after_collision_battle/` | 862 | Pod timeout after >50 collisions. |
| 12 | `14_elim_shield_war/` | 568 | Pod timeout with 15+ SHIELD. |
| 13 | `15_elim_pod_timeout_standard/` | 164 | Standard pod/checkpoint timeout. |

## META mirror folders (additional copies)

| Folder | Count | Description |
|--------|------:|-------------|
| `18_timeout_yes_any/` | 1604 | All timeout-related battles |
| `19_timeout_no_clean_finish/` | 15368 | Clean endReached only |

## Files

- `manifest.csv` — per-battle labels and metrics
- `../categorize_battles.py` — re-runnable script
