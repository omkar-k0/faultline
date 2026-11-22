# Generated tests on dev: mutation score

Command `faultline testgen eval --split dev`. Tests learned from 30 clean train runs only: court_cases 29 tests, 441 checks; jaffle_shop 8 tests, 107 checks; stripe 117 tests, 4276 checks. A faulted run is caught when a generated test fails on it (real dbt test, rebuilt run).

| Fault type | n | Generated tests | Project's own tests | Either |
|---|---|---|---|---|
| schema_change | 6 | 100.0% (6/6) | 0.0% (0/6) | 100.0% (6/6) |
| late_or_missing_data | 6 | 100.0% (6/6) | 0.0% (0/6) | 100.0% (6/6) |
| duplicate_keys | 6 | 100.0% (6/6) | 66.7% (4/6) | 100.0% (6/6) |
| null_spike | 6 | 100.0% (6/6) | 0.0% (0/6) | 100.0% (6/6) |
| distribution_shift | 6 | 66.7% (4/6) | 0.0% (0/6) | 66.7% (4/6) |
| model_logic_bug | 6 | 16.7% (1/6) | 0.0% (0/6) | 16.7% (1/6) |
| broken_join | 6 | 100.0% (6/6) | 50.0% (3/6) | 100.0% (6/6) |
| timezone_error | 6 | 50.0% (3/6) | 0.0% (0/6) | 50.0% (3/6) |
| **all faulted (mutation score)** | 48 | 79.2% (38/48) | 14.6% (7/48) | 79.2% (38/48) |

False alarms: clean runs where a generated test failed 3.3% (1/30); where the project's own tests failed 0.0% (0/30).
Generated tests that failed on a clean run: `faultline_gen_m_stg_stripe__account_tmp`, `faultline_gen_s_account_data`, `faultline_gen_src_account`.
