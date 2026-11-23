# triage_llm.reference on heldout

Config hash `8993f12427f3` · archive `sha256:8fe3c87c2658…` · command `faultline eval --split heldout --baseline triage_llm --reference`

| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |
|---|---|---|---|---|---|---|
| schema_change | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| late_or_missing_data | 6 | 100.0% (6/6) | 50.0% (3/6) | 66.7% (4/6) | 50.0% (3/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| null_spike | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 16.7% (1/6) | 16.7% (1/6) | 16.7% (1/6) | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 50.0% (3/6) | 50.0% (3/6) | 50.0% (3/6) | 0.0% (0/6) | 0.0% (0/6) |
| broken_join | 6 | 66.7% (4/6) | 66.7% (4/6) | 66.7% (4/6) | 0.0% (0/6) | 0.0% (0/6) |
| timezone_error | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 79.2% (38/48) | 72.9% (35/48) | 75.0% (36/48) | 6.2% (3/48) | 0.0% (0/48) |

## The gate

- Answered (a cause given): 38 of 38 detected faulted runs; right at top-1 when answering: 92.1% (35/38).
- Not confirmed: 0; correct not confirmed: n/a (abstained, and the best untested cause would have been wrong).
- Without the tests (every proposed cause ranked) top-1 would be 20.8% (10/48).

False alarms on clean runs: 10.0% (1/10).

Diagnostic, not a score: right node at top-1 79.2% (38/48), in top-3 79.2% (38/48) (column and commit ignored).

Top-1 and top-3 count a root cause only at location level: node, column where the truth has one, commit for code faults. See docs/EVAL.md.
