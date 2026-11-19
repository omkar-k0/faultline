# Status

Updated 2026-11-19, afternoon.

## Current milestone

M5 Incident manager + triage agent, issue #18. Built in two PRs:
- **M5a**: incident manager, hypotheses, tests, deterministic ranking. Merged (PR #19).
- **M5b** (branch `m5b-ablations`, draft PR): the three ablations, the gate metrics including "correct not confirmed", and the LLM re-ranker. Waiting on one run: `make eval-dev-triage-llm` on the owner's Mac (docs/EVAL.md).

## Done in M5b

- Generator fix: data faults that change no file are skipped. Train benchmark-fix for `inc_stripe_train_019` (a no-op), train regenerated as `benchmark-train-2.tar.gz`; train monitors and triage re-run. **The new asset still has to be uploaded to release benchmark-v1 by the owner** (file in Downloads); until then a clean clone cannot fetch train.

- `triage/llm_rank.py`: re-ranker prompt, answer parsing; the agent's RERANK state lets it only permute survivors.
- `faultline eval --baseline triage --ablate tests|lineage`, `--baseline triage_llm`; `eval/results/<split>/ablations.md` built from the result files.
- Gate metrics in every triage result: answered, right when answering, not confirmed, correct not confirmed, untested top-1.
- Dev results: no LLM ranker top-1 89.6% (43/48); no tests 39.6% (19/48) with wrong top-1 50.0% (24/48); no lineage 87.5% (42/48). From `eval/results/dev/ablations.md`.
- Tests: 21 in `tests/test_triage.py`, plus a fake-model end-to-end run of `triage_llm`; the ablation results reproduce byte for byte.

## Done in M5a

- `triage/evidence.py`: symptoms from monitor anomalies and failed dbt tests or models; skipped nodes kept apart; the run's own lineage, cached by its compiled SQL and columns.
- `incidents/manager.py`: symptoms grouped into incidents by table lineage. `incidents/store.py`: incidents and reports in a DuckDB file.
- `triage/hypotheses.py`: data causes at seeds and sources, code causes at models with the commit that changed them (a file's creating commit is never a cause).
- `triage/checks.py`: one test per cause, run on recorded aggregates, lineage, compiled SQL and history; causes inferred by elimination for changes through unmeasured (text) inputs.
- `triage/agent.py`: the state machine gather -> group -> propose -> test -> rank -> report; survivors only, "not confirmed" when none.
- `faultline eval --baseline triage`, `faultline triage <run id>` (prints the report, stores it in `build/faultline.duckdb`).
- Results: `eval/results/dev/triage.*` (top-1 89.6%, 43/48; wrong top-1 0/48; false alarms 0/30) and, as a one-time check, `eval/results/train/triage.*` (M5a: top-1 88.5%, 85/96; after the train benchmark-fix: 89.6%, 86/96, wrong top-1 3/96, false alarms 0/30). Both reproduce byte for byte (test).
- Tests: 193 passing, including `tests/test_triage.py` (13, one property test).

## Done in M4

- `monitors/core.py`: seven checks on table profiles (schema, volume, freshness, null rate, distribution, duplicates, time shift), settings in `faultline.toml` `[monitors]`.
- `monitors/method.py`: known-good reference picker (9 of 10 clean runs, same project and split) and upstream-first ranking of anomalies.
- `faultline eval --baseline monitors`; results in `eval/results/dev/monitors.*` and `eval/results/train/monitors.*`, both reproducible byte for byte (test). The result table includes which monitor fired per fault type.
- Unit and property tests in `tests/test_monitors.py`.

## Done in M3

- `eval/loader.py`: downloads the split archive from release `benchmark-v1`, checks its sha256 against the manifest, extracts safely; methods see run files and a cleaned git history only (injector messages and seed-data commits removed; leak test on every dev run).
- `eval/score.py`: location-level matching (node or physical node, column when the truth has one, commit for code faults); detection, top-1, top-3, wrong top-1, not confirmed, false alarms on clean runs; node-only diagnostic. Property tests.
- `eval/baselines.py`: `dbt_tests` (alert only), `dbt_tests_guess` (alert plus naive cause), `raw_log_llm` (local model, strict JSON).
- `llm/client.py`: `LLMClient` and an OpenAI-compatible client on the standard library; `faultline.toml` points at Ollama with `qwen2.5:7b-instruct`.
- `faultline eval`, `make eval-dev`, `make eval-dev-llm`, `make fetch-benchmark`.
- Results committed: `eval/results/dev/dbt_tests.*` and `eval/results/dev/dbt_tests_guess.*`. A test checks they reproduce byte for byte.
- `docs/EVAL.md`: metrics, baselines, how to run the LLM baseline, known weaknesses.

## Done

- M0 scaffold and M1 lineage: merged (PRs #4 and #6).
- `src/faultline/inject/`: workspace copy with its own git history, fault catalog, natural variation (2% noise on numeric measures), the 8 fault types, dbt run and aggregate profiling, ground truth, benchmark generator.
- CLI: `faultline inject`, `faultline benchmark generate`, `faultline benchmark summary`; `make benchmark SPLIT=<name>`.
- `projects/court_cases`: our own synthetic court case lifecycle project (seeded generator, 20 models, 75 dbt tests pass, 158 columns, 0 unresolved lineage). Added to train and dev.
- `benchmark/plan.toml`: train and dev on jaffle_shop, stripe and court_cases.
- Generated and committed (regenerated after court_cases joined): `benchmark/train/` (96 faulted, 12 per type, plus 30 clean runs) and `benchmark/dev/` (48 faulted, 6 per type, plus 30 clean runs), with `benchmark/manifest.json`. 0 skipped. All 60 clean runs pass dbt. No seed or model is faulted in both splits.
- Archives `dist/benchmark-train.tar.gz` (30 MB) and `dist/benchmark-dev.tar.gz` (19 MB); their sha256 is in the manifest. Published as pre-release `benchmark-v1` (https://github.com/omkar-k0/faultline/releases/tag/benchmark-v1); downloaded assets verified against the manifest hashes on 2026-11-19.
- Reproducibility checked on the first generation: two train incidents (one data, one code fault) regenerated byte-identical `truth.json`, commit hash included. The court_cases seed generator reproduces its CSV files byte for byte (tested).
- `heldout-guard` allows one additions-only PR labelled `heldout-freeze` while heldout is empty; label created. Procedure in `docs/BENCHMARK.md`.
- Held-out split frozen: 58 runs on `jira` (48 faulted, 6 per type, plus 10 clean), generated by the owner on his machine, 0 skipped. Merged into `m2-benchmark` by #10 (guard passed in freeze mode), then into `main` by #11. Archive `benchmark-heldout.tar.gz` is on release `benchmark-v1`; its sha256 matches the manifest. Its contents were not opened in the coding session.
- Tests: 125 passing, including the recoverability property test for every fault type on all three projects.

## Not verified

- "Not confirmed" never fired on dev or train, so "correct not confirmed" has no cases (n/a).
- The full variant with the LLM re-ranker has not been run with a real model yet.

- M1 hand-check sheet: still not filled in.
- CODEOWNERS enforcement: needs branch protection on `main`.

## Known weaknesses

- Clean runs do not vary in volume (rows are never dropped), so false alarms on volume in M4 are an easy test.
- Variant mix is random with few draws per type, so some variants are rare (for example schema-change drops). Spreading variants evenly would need a new generation of train and dev.
- court_cases is synthetic and written by us: cleaner than real court data. Real public data is a later step, after a licence check.
- jaffle_shop has few fault sites; with node-level splits, jaffle train has no timezone candidate, so stripe carries those.
- Code faults name an output column only when the change sits inside one (7 of 24 in train); otherwise the location is the model and the commit.

## Open decisions

- None for M2: the held-out project is fivetran/dbt_jira (owner's choice), vendored in `projects/jira`, builds offline (110 of 110 pass, 61 models, 0 unresolved lineage columns).

## Broken

- Nothing known.

## Next step

- Later: research real public court data and its licences; build the web viewer from the Stitch designs (real content only).
- Owner: review PR #17.
- Then M5: incident manager and triage agent. Plan first.
