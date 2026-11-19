# raw_log_llm on dev

Config hash `5b3bbd60c1f8` · archive `sha256:4b03de862025…` · command `faultline eval --split dev --baseline raw_log_llm`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 66.7% (4/6) | 0.0% (0/6) | 0.0% (0/6) | 66.7% (4/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 33.3% (2/6) | 0.0% (0/6) | 0.0% (0/6) | 33.3% (2/6) | 0.0% (0/6) |
| null_spike | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| broken_join | 6 | 33.3% (2/6) | 16.7% (1/6) | 16.7% (1/6) | 16.7% (1/6) | 0.0% (0/6) |
| timezone_error | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 16.7% (8/48) | 2.1% (1/48) | 2.1% (1/48) | 14.6% (7/48) | 0.0% (0/48) |

False alarms on clean runs: 0.0% (0/30).

Diagnostic, not a score: right node at top-1 2.1% (1/48), in top-3 2.1% (1/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
