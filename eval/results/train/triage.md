# triage on train

Config hash `d7723c98f207` · archive `sha256:e620ba7d6d1c…` · command `faultline eval --split train --baseline triage`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) |
| late_or_missing_data | 12 | 100.0% (12/12) | 83.3% (10/12) | 91.7% (11/12) | 16.7% (2/12) | 0.0% (0/12) |
| duplicate_keys | 12 | 100.0% (12/12) | 91.7% (11/12) | 100.0% (12/12) | 8.3% (1/12) | 0.0% (0/12) |
| null_spike | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) |
| distribution_shift | 12 | 58.3% (7/12) | 58.3% (7/12) | 58.3% (7/12) | 0.0% (0/12) | 0.0% (0/12) |
| model_logic_bug | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) |
| broken_join | 12 | 100.0% (12/12) | 100.0% (12/12) | 100.0% (12/12) | 0.0% (0/12) | 0.0% (0/12) |
| timezone_error | 12 | 83.3% (10/12) | 83.3% (10/12) | 83.3% (10/12) | 0.0% (0/12) | 0.0% (0/12) |
| **all faulted** | 96 | 92.7% (89/96) | 89.6% (86/96) | 91.7% (88/96) | 3.1% (3/96) | 0.0% (0/96) |

## The gate

- Answered (a cause given): 89 of 89 detected faulted runs; right at top-1 when answering: 96.6% (86/89).
- Not confirmed: 0; correct not confirmed: n/a (abstained, and the best untested cause would have been wrong).
- Without the tests (every proposed cause ranked) top-1 would be 36.5% (35/96).

False alarms on clean runs: 0.0% (0/30).

Diagnostic, not a score: right node at top-1 92.7% (89/96), in top-3 92.7% (89/96) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
