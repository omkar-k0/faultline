# monitors on heldout

Config hash `93f805f53942` · archive `sha256:8fe3c87c2658…` · command `faultline eval --split heldout --baseline monitors`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 100.0% (6/6) | 50.0% (3/6) | 50.0% (3/6) | 50.0% (3/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 100.0% (6/6) | 66.7% (4/6) | 83.3% (5/6) | 33.3% (2/6) | 0.0% (0/6) |
| null_spike | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 16.7% (1/6) | 16.7% (1/6) | 16.7% (1/6) | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 50.0% (3/6) | 0.0% (0/6) | 0.0% (0/6) | 50.0% (3/6) | 0.0% (0/6) |
| broken_join | 6 | 66.7% (4/6) | 0.0% (0/6) | 0.0% (0/6) | 66.7% (4/6) | 0.0% (0/6) |
| timezone_error | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 79.2% (38/48) | 54.2% (26/48) | 56.2% (27/48) | 25.0% (12/48) | 0.0% (0/48) |

## Which monitor fired (incidents per fault type)

| Monitor | schema_change | late_or_missing_data | duplicate_keys | null_spike | distribution_shift | model_logic_bug | broken_join | timezone_error | clean (false alarms) |
|---|---|---|---|---|---|---|---|---|---|
| schema | 6 | 4 | 2 | 0 | 0 | 3 | 2 | 0 | 0 |
| volume | 0 | 6 | 3 | 1 | 0 | 0 | 4 | 0 | 0 |
| freshness | 3 | 4 | 0 | 1 | 0 | 0 | 1 | 5 | 0 |
| null_rate | 4 | 3 | 4 | 6 | 1 | 0 | 2 | 0 | 0 |
| distribution | 0 | 2 | 3 | 0 | 1 | 0 | 3 | 2 | 1 |
| duplicates | 1 | 0 | 5 | 0 | 0 | 0 | 3 | 1 | 0 |
| time_shift | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |

False alarms on clean runs: 10.0% (1/10).

Diagnostic, not a score: right node at top-1 75.0% (36/48), in top-3 75.0% (36/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
