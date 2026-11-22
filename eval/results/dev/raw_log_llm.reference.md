# raw_log_llm.reference on dev

Config hash `e27137ddb640` · archive `sha256:4b03de862025…` · command `faultline eval --split dev --baseline raw_log_llm --reference`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 83.3% (5/6) | 83.3% (5/6) | 83.3% (5/6) | 0.0% (0/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 50.0% (3/6) | 50.0% (3/6) | 50.0% (3/6) | 0.0% (0/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 66.7% (4/6) | 66.7% (4/6) | 66.7% (4/6) | 0.0% (0/6) | 0.0% (0/6) |
| null_spike | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 100.0% (6/6) |
| broken_join | 6 | 100.0% (6/6) | 50.0% (3/6) | 50.0% (3/6) | 0.0% (0/6) | 50.0% (3/6) |
| timezone_error | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 50.0% (24/48) | 31.2% (15/48) | 31.2% (15/48) | 0.0% (0/48) | 18.8% (9/48) |

False alarms on clean runs: 0.0% (0/30).

Diagnostic, not a score: right node at top-1 31.2% (15/48), in top-3 31.2% (15/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
