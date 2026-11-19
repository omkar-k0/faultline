# monitors on train

Config hash `ae2c949aae4f` · archive `sha256:cf3b50902a87…` · command `faultline eval --split train --baseline monitors`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) |
| late_or_missing_data | 12 | 100.0% (12/12) | 91.7% (11/12) | 91.7% (11/12) | 8.3% (1/12) | 0.0% (0/12) |
| duplicate_keys | 12 | 100.0% (12/12) | 25.0% (3/12) | 41.7% (5/12) | 75.0% (9/12) | 0.0% (0/12) |
| null_spike | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) |
| distribution_shift | 12 | 50.0% (6/12) | 50.0% (6/12) | 50.0% (6/12) | 0.0% (0/12) | 0.0% (0/12) |
| model_logic_bug | 12 | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) | 100.0% (12/12) | 0.0% (0/12) |
| broken_join | 12 | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) | 100.0% (12/12) | 0.0% (0/12) |
| timezone_error | 12 | 83.3% (10/12) | 83.3% (10/12) | 83.3% (10/12) | 0.0% (0/12) | 0.0% (0/12) |
| **all faulted** | 96 | 91.7% (88/96) | 56.2% (54/96) | 58.3% (56/96) | 35.4% (34/96) | 0.0% (0/96) |

## Which monitor fired (incidents per fault type)

| Monitor | schema_change | late_or_missing_data | duplicate_keys | null_spike | distribution_shift | model_logic_bug | broken_join | timezone_error | clean (false alarms) |
|---|---|---|---|---|---|---|---|---|---|
| schema | 12 | 10 | 6 | 0 | 0 | 7 | 0 | 1 | 0 |
| volume | 0 | 12 | 9 | 1 | 0 | 0 | 12 | 0 | 0 |
| freshness | 1 | 7 | 0 | 1 | 0 | 0 | 0 | 5 | 0 |
| null_rate | 2 | 7 | 1 | 12 | 0 | 0 | 1 | 0 | 0 |
| distribution | 1 | 2 | 2 | 5 | 6 | 8 | 7 | 0 | 0 |
| duplicates | 0 | 0 | 5 | 0 | 0 | 0 | 2 | 0 | 0 |
| time_shift | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |

False alarms on clean runs: 0.0% (0/30).

Diagnostic, not a score: right node at top-1 91.7% (88/96), in top-3 91.7% (88/96) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
