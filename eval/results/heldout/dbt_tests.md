# dbt_tests on heldout

Config hash `aeee888f69bb` · archive `sha256:8fe3c87c2658…` · command `faultline eval --split heldout --baseline dbt_tests`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 16.7% (1/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 16.7% (1/6) |
| duplicate_keys | 6 | 33.3% (2/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 33.3% (2/6) |
| null_spike | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| broken_join | 6 | 33.3% (2/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 33.3% (2/6) |
| timezone_error | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 10.4% (5/48) | 0.0% (0/48) | 0.0% (0/48) | 0.0% (0/48) | 10.4% (5/48) |

False alarms on clean runs: 0.0% (0/10).

Diagnostic, not a score: right node at top-1 0.0% (0/48), in top-3 0.0% (0/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
