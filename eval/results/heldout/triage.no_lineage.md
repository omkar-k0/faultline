# triage.no_lineage on heldout

Config hash `c9c2637a5f74` · archive `sha256:8fe3c87c2658…` · command `faultline eval --split heldout --baseline triage --ablate lineage`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 100.0% (6/6) | 50.0% (3/6) | 66.7% (4/6) | 50.0% (3/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| null_spike | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 16.7% (1/6) | 16.7% (1/6) | 16.7% (1/6) | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 50.0% (3/6) | 50.0% (3/6) | 50.0% (3/6) | 0.0% (0/6) | 0.0% (0/6) |
| broken_join | 6 | 66.7% (4/6) | 33.3% (2/6) | 33.3% (2/6) | 0.0% (0/6) | 33.3% (2/6) |
| timezone_error | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 79.2% (38/48) | 68.8% (33/48) | 70.8% (34/48) | 6.2% (3/48) | 4.2% (2/48) |

## The gate

- Answered (a cause given): 36 of 38 detected faulted runs; right at top-1 when answering: 91.7% (33/36).
- Not confirmed: 2; correct not confirmed: 100.0% (2/2) (abstained, and the best untested cause would have been wrong).
- Without the tests (every proposed cause ranked) top-1 would be 29.2% (14/48).

False alarms on clean runs: 10.0% (1/10).

Diagnostic, not a score: right node at top-1 75.0% (36/48), in top-3 75.0% (36/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
