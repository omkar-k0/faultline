# raw_log_llm.reference on heldout

Config hash `6d22ce2bdb25` · archive `sha256:8fe3c87c2658…` · command `faultline eval --split heldout --baseline raw_log_llm --reference`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 16.7% (1/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 16.7% (1/6) |
| late_or_missing_data | 6 | 16.7% (1/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 16.7% (1/6) |
| duplicate_keys | 6 | 33.3% (2/6) | 0.0% (0/6) | 0.0% (0/6) | 33.3% (2/6) | 0.0% (0/6) |
| null_spike | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 100.0% (6/6) | 16.7% (1/6) | 16.7% (1/6) | 0.0% (0/6) | 83.3% (5/6) |
| broken_join | 6 | 100.0% (6/6) | 50.0% (3/6) | 50.0% (3/6) | 0.0% (0/6) | 50.0% (3/6) |
| timezone_error | 6 | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 33.3% (16/48) | 8.3% (4/48) | 8.3% (4/48) | 4.2% (2/48) | 20.8% (10/48) |

False alarms on clean runs: 0.0% (0/10).

Diagnostic, not a score: right node at top-1 8.3% (4/48), in top-3 8.3% (4/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
