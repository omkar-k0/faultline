# raw_log_llm.mlx_raw_log on heldout

Config hash `8af8d31868b4` · archive `sha256:8fe3c87c2658…` · command `faultline eval --split heldout --baseline raw_log_llm --llm-profile mlx_raw_log`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 33.3% (2/6) | 16.7% (1/6) | 16.7% (1/6) | 16.7% (1/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 83.3% (5/6) | 0.0% (0/6) | 0.0% (0/6) | 83.3% (5/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 50.0% (3/6) | 0.0% (0/6) | 0.0% (0/6) | 50.0% (3/6) | 0.0% (0/6) |
| null_spike | 6 | 16.7% (1/6) | 0.0% (0/6) | 0.0% (0/6) | 16.7% (1/6) | 0.0% (0/6) |
| distribution_shift | 6 | 33.3% (2/6) | 0.0% (0/6) | 0.0% (0/6) | 33.3% (2/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 16.7% (1/6) | 0.0% (0/6) | 0.0% (0/6) | 16.7% (1/6) | 0.0% (0/6) |
| broken_join | 6 | 33.3% (2/6) | 0.0% (0/6) | 0.0% (0/6) | 33.3% (2/6) | 0.0% (0/6) |
| timezone_error | 6 | 50.0% (3/6) | 0.0% (0/6) | 0.0% (0/6) | 50.0% (3/6) | 0.0% (0/6) |
| **all faulted** | 48 | 39.6% (19/48) | 2.1% (1/48) | 2.1% (1/48) | 37.5% (18/48) | 0.0% (0/48) |

False alarms on clean runs: 20.0% (2/10).

Diagnostic, not a score: right node at top-1 2.1% (1/48), in top-3 2.1% (1/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
