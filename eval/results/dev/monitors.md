# monitors on dev

Config hash `f33c88c9e810` · archive `sha256:4b03de862025…` · command `faultline eval --split dev --baseline monitors`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 100.0% (6/6) | 33.3% (2/6) | 33.3% (2/6) | 66.7% (4/6) | 0.0% (0/6) |
| null_spike | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 66.7% (4/6) | 50.0% (3/6) | 50.0% (3/6) | 16.7% (1/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 83.3% (5/6) | 0.0% (0/6) | 0.0% (0/6) | 83.3% (5/6) | 0.0% (0/6) |
| broken_join | 6 | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) | 100.0% (6/6) | 0.0% (0/6) |
| timezone_error | 6 | 66.7% (4/6) | 66.7% (4/6) | 66.7% (4/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 89.6% (43/48) | 56.2% (27/48) | 56.2% (27/48) | 33.3% (16/48) | 0.0% (0/48) |

## Which monitor fired (incidents per fault type)

| Monitor | schema_change | late_or_missing_data | duplicate_keys | null_spike | distribution_shift | model_logic_bug | broken_join | timezone_error | clean (false alarms) |
|---|---|---|---|---|---|---|---|---|---|
| schema | 6 | 5 | 4 | 0 | 0 | 2 | 1 | 0 | 0 |
| volume | 0 | 6 | 4 | 0 | 0 | 0 | 6 | 0 | 0 |
| freshness | 0 | 4 | 0 | 2 | 1 | 3 | 1 | 2 | 0 |
| null_rate | 1 | 5 | 1 | 6 | 0 | 0 | 1 | 0 | 0 |
| distribution | 1 | 3 | 2 | 0 | 4 | 1 | 3 | 1 | 0 |
| duplicates | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |
| time_shift | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 |

False alarms on clean runs: 0.0% (0/30).

Diagnostic, not a score: right node at top-1 87.5% (42/48), in top-3 87.5% (42/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
