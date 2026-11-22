# Status

Updated 2026-11-23.

## Current milestone

M7 Fix drafter + test generator, issue #25, branch `m7-fixes-testgen` (draft PR). M6 is done (PRs #23, #24). Next: M8, MCP server, reports, held-out scored once, release (plan first).

## Done in M7

- `inject/rebuild.py`: exact rebuilds of train and dev runs, checked against the recorded input hash; held-out refused.
- `fixes/`: drafter (revert a model commit, dedupe a duplicated source key, map a renamed seed column; no code fix for data faults), draft PR writer (`gh pr create --draft`, never merges), scoring.
- `testgen/`: checks learned from train clean runs, one warn-level singular test per relation, mutation scoring with the failed checks named.
- Dev results: fixes 16/48 fixed, 16/16 when proposed, 0/30 on clean runs (`eval/results/dev/fixes.md`); generated tests catch 38/48 vs 7/48 for the projects' own tests, 1/30 clean runs with a false alarm (`eval/results/dev/testgen.md`).
- `make eval-dev-fixes`, `make eval-dev-testgen` (about 160 dbt builds; not in `make check`). Tests: 236 passing.
- Not verified: a live draft PR on a real repo (waits for M8 and the owner's OK).

## Done in M6b

- Both LoRA adapters trained on the owner's MacBook Air (M4, 16 GB), mlx-lm 0.32.2, from `benchmark/train/` only: ranker 330 steps (validation loss 2.039 to 0.003), raw-log 230 steps (0.650 to 0.059). Adapters are not committed; each result records the adapter's sha256.
- Dev results, from `eval/results/dev/llm_slots.md`:
  - Ranking slot: rules 89.6% top-1 (43/48), 0 wrong; base MLX 87.5% (42/48), 1 wrong; tuned 89.6% (43/48), 0 wrong; Claude Opus 5.5 87.5% (42/48), 1 wrong, $0.0057 per incident.
  - Raw-log slot: base MLX 2.1% (1/48), 6 wrong; tuned 4.2% (2/48), 9 wrong; Claude Opus 5.5 31.2% (15/48), 0 wrong, 9 not confirmed, $0.0408 per incident.
- Reference spend on dev: $3.18 (raw-log, 78 calls) + $0.44 (ranking, 57 calls). A first ranking run hit the account's usage limit on 26 calls; the harness now marks such a run incomplete, and it was run again in full.
- Not verified: the reference answers repeat run to run (Opus 5.5 takes no temperature).

## Done in M6a

- `faultline finetune export --slot ranker|raw_log` (train only): 166 ranker training examples from 77 incidents (23 validation from 11); 115 raw-log training runs (11 validation), 43 of them labelled with a cause.
- `finetune/ranker.yaml`, `finetune/raw_log.yaml` for `mlx_lm.lora`; `mlx` dependency group (mlx-lm 0.32.2, Mac only, not installed in CI).
- `[llm.profiles.*]` in faultline.toml and `faultline eval --llm-profile`; results named `<method>.<profile>`, with the adapter's hash.
- `llm/reference.py`: Claude through the Messages API, key from the environment only, cost from usage, cap checked before each call, retries on overload, `--dry-run` via token counting.
- `eval/results/dev/llm_slots.md`: both slots, local rows and the reference apart.
- Not verified: training memory on a 16 GB Mac for the long raw-log prompts; the Opus 5.5 model string and temperature setting against the live API (the dry run will show both).

## Done in M5c (LLM re-ranker run)

- `make eval-dev-triage-llm` run on the owner's MacBook Air (Apple M4, Ollama 0.40.16, `qwen2.5:7b-instruct`, context 16384), at commit 2854460, config hash `d987e933a701`. Files: `eval/results/dev/triage_llm.*`.
- Full variant (tests, lineage, re-ranker) top-1 87.5% (42/48), wrong top-1 1/48, false alarms 0/30. The deterministic ranking scores 89.6% (43/48), wrong top-1 0/48. From `eval/results/dev/ablations.md`.
- 57 re-rank calls, 0 unusable answers; the model changed the top cause in 8 incidents, and that changed the score in one (`inc_court_cases_dev_004`: it put the table-level cause above the late column, which is the truth; still in top-3).

## Done in M5b

- Generator fix: data faults that change no file are skipped. Train benchmark-fix for `inc_stripe_train_019` (a no-op), train regenerated as `benchmark-train-2.tar.gz`; train monitors and triage re-run. The new asset is on release benchmark-v1 (uploaded by the owner).

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
