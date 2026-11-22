# triage_llm.mlx_base on dev

Config hash `d0fa0e3000e5` · archive `sha256:4b03de862025…` · command `faultline eval --split dev --baseline triage_llm --llm-profile mlx_base`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 100.0% (6/6) | 83.3% (5/6) | 100.0% (6/6) | 16.7% (1/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| null_spike | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 66.7% (4/6) | 66.7% (4/6) | 66.7% (4/6) | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 83.3% (5/6) | 83.3% (5/6) | 83.3% (5/6) | 0.0% (0/6) | 0.0% (0/6) |
| broken_join | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| timezone_error | 6 | 66.7% (4/6) | 66.7% (4/6) | 66.7% (4/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 89.6% (43/48) | 87.5% (42/48) | 89.6% (43/48) | 2.1% (1/48) | 0.0% (0/48) |

## The gate

- Answered (a cause given): 43 of 43 detected faulted runs; right at top-1 when answering: 97.7% (42/43).
- Not confirmed: 0; correct not confirmed: n/a (abstained, and the best untested cause would have been wrong).
- Without the tests (every proposed cause ranked) top-1 would be 39.6% (19/48).

False alarms on clean runs: 0.0% (0/30).

Diagnostic, not a score: right node at top-1 89.6% (43/48), in top-3 89.6% (43/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
