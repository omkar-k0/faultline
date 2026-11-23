# Fix drafter on dev

Command `faultline fix eval --split dev`. A fix succeeds when dbt build passes and every model equals the same run built without its fault.

| Fault type | n | Fix proposed | Fixed |
|---|---|---|---|
| schema_change | 6 | 16.7% (1/6) | 16.7% (1/6) |
| late_or_missing_data | 6 | 0.0% (0/6) | 0.0% (0/6) |
| duplicate_keys | 6 | 66.7% (4/6) | 66.7% (4/6) |
| null_spike | 6 | 0.0% (0/6) | 0.0% (0/6) |
| distribution_shift | 6 | 0.0% (0/6) | 0.0% (0/6) |
| model_logic_bug | 6 | 83.3% (5/6) | 83.3% (5/6) |
| broken_join | 6 | 100.0% (6/6) | 100.0% (6/6) |
| timezone_error | 6 | 0.0% (0/6) | 0.0% (0/6) |
| **all faulted** | 48 | 33.3% (16/48) | 33.3% (16/48) |

Fixed when a fix was proposed: 100.0% (16/16). Fixes proposed on clean runs: 0.0% (0/30).

| Pattern | Fixed / proposed |
|---|---|
| dedupe_rows | 100.0% (4/4) |
| map_renamed_column | 100.0% (1/1) |
| revert_commit | 100.0% (11/11) |
