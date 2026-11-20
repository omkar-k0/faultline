# Decisions

Each entry: decision, alternative, reason.

## 2026-11-18: First test project is jaffle_shop_duckdb
- Decision: vendor dbt-labs/jaffle_shop_duckdb at a pinned commit into `projects/jaffle_shop/`.
- Alternative: write a toy project ourselves.
- Reason: a well-known open project (Apache 2.0) makes results credible and builds on DuckDB in seconds.

## 2026-11-18: Stay on dbt Core v1
- Decision: pin `dbt-core>=1.11,<2`.
- Alternative: dbt v2, which dbt now announces as the default for new installs.
- Reason: the vendored projects target v1, and the artefact formats faultline reads are documented for v1. Revisit after M2.

## 2026-11-18: Full stack added at M0
- Decision: add `sqlglot`, `networkx` and `hypothesis` now, with dbt and the dev tools.
- Alternative: add each when first used.
- Reason: owner's choice, so `uv.lock` is settled before M1.

## 2026-11-18: heldout-guard uses one allowlisted file
- Decision: any added `src/` line matching "heldout" (also "held_out", "held-out") fails, except in `src/faultline/eval/splits.py`.
- Alternative: block every mention in `src/`.
- Reason: `faultline eval --split heldout` must name the split somewhere. One owner-reviewed file keeps that in a single place.

## 2026-11-18: The guard and CI files are owner-reviewed
- Decision: CODEOWNERS covers `benchmark/heldout/`, the guard script, the workflows and CODEOWNERS itself.
- Alternative: cover only `benchmark/heldout/`.
- Reason: otherwise a PR could weaken the guard and touch heldout in the same change.

## 2026-11-18: CLI uses argparse
- Decision: plain `argparse`.
- Alternative: typer or click.
- Reason: no extra dependency for a handful of subcommands.

## 2026-11-18: Second test project is fivetran dbt_stripe, with its packages vendored
- Decision: vendor dbt_stripe plus fivetran_utils, spark_utils and dbt_utils as local packages.
- Alternative: let `dbt deps` fetch them from the dbt package hub.
- Reason: the build then needs no network and every package is pinned; the hub is unreachable from the cloud session.

## 2026-11-18: Seed before build, and test that models hold rows
- Decision: `make build-projects` runs `dbt seed` before `dbt build`, and a test fails if any model is empty outside a pinned list.
- Alternative: trust a green `dbt build`.
- Reason: the first stripe build passed 105 of 105 with every staging table empty, because dbt read the sources before the seeds loaded.

## 2026-11-18: Column lineage tracks value flow, one dbt hop per edge
- Decision: edges come from sqlglot projection lineage on compiled SQL. Join keys, WHERE and GROUP BY columns are not edges. Each edge goes one dbt model back; longer chains come from the graph.
- Alternative: also record filter and join columns as edges.
- Reason: impact and root cause first need where values come from. Join keys matter for broken-join faults and get their own edge type when M5 needs them.

## 2026-11-18: Lineage follows the SQL, not dbt's depends_on
- Decision: when compiled SQL reads a relation missing from `depends_on`, keep the edge and report it as undeclared.
- Alternative: drop edges dbt did not declare.
- Reason: the SQL is what runs. dbt_stripe has two such models; hiding them would hide a real source of incidents.

## 2026-11-18: One sqlglot pass per model
- Decision: call `sqlglot.lineage` once per model for all columns, falling back to one column at a time only if that fails.
- Alternative: one call per column.
- Reason: stripe lineage went from 31 s to 7 s with the same result.

## 2026-11-18: Natural variation without dropping rows
- Decision: clean and faulted runs start from seed data with 2% noise on numeric measures; rows are never dropped.
- Alternative: keep 90-100% of rows, as first planned.
- Reason: dropping payment rows left orders without payments and failed `not_null` tests on clean runs. Cost: clean runs do not vary in volume, so the volume false-alarm test in M4 is weaker. Listed as a known weakness.

## 2026-11-18: Splits are disjoint by node, not only by column
- Decision: within a project, every seed and every model belongs to exactly one split.
- Alternative: disjoint (node, column) pairs.
- Reason: root cause is scored at node level too; a node shared between train and dev would leak.

## 2026-11-18: Code faults must change something
- Decision: a code fault is kept only if the build fails or a table profile differs from the clean run with the same seed; otherwise the next site is tried (up to 6).
- Alternative: keep every mutation.
- Reason: an equivalent mutant is an incident with no symptom and no correct answer.

## 2026-11-18: Heldout is frozen by one labelled PR from the owner
- Decision: `heldout-guard` allows one additions-only PR labelled `heldout-freeze`, only while `benchmark/heldout/` is empty on the base. The owner generates heldout on his machine.
- Alternative: generate heldout in the coding session.
- Reason: whoever writes rules and prompts must never see heldout incidents.

## 2026-11-18: dbt runs in one process per incident
- Decision: `deps`, `seed`, `build` and `docs generate` run through `dbtRunner` in one subprocess.
- Alternative: four `dbt` commands.
- Reason: one Python start and one parse instead of four; a stripe run went from about 35 s to about 22 s.

## 2026-11-18: Ground truth carries `physical` and `file` besides `node`
- Decision: `location` has `node` (what models read), `column`, `commit`, plus `physical` (where the change was written) and `file`.
- Alternative: only node, column, commit, as in the approved schema.
- Reason: for stripe the models read a source while the change is written to a seed; scoring uses `node`, the other two make every incident checkable by hand.

## 2026-11-18: A third train/dev project of our own: court_cases
- Decision: add `projects/court_cases`, a synthetic court case lifecycle project written for faultline (seeded generator, 20 models), to train and dev; train and dev were regenerated.
- Alternative: use it as the held-out project, or stay with two projects.
- Reason: more domain variety and fault sites (local court times make timezone faults realistic) and a demo domain for the viewer. It cannot be held-out: the same hand writes it and the triage rules. Real public court data may replace or join it later, after a licence check.

## 2026-11-19: The held-out project is fivetran/dbt_jira
- Decision: vendor dbt_jira (Apache 2.0, 61 models) as the project used only by the held-out split; owner's choice.
- Alternative: dbt_zendesk, dbt_github, or tuva-health/demo.
- Reason: a new domain (project management) at stripe's size, building offline with the same pinned packages. Weakness: same vendor coding style as stripe.

## 2026-11-19: Record of how heldout reached main
- Decision: accept the freeze on `main` as merged by #11, without the `heldout-freeze` label (the guard failed there).
- Alternative: revert #11 and redo it with the label.
- Reason: #11 changed exactly the files that #10 froze (58 added held-out files, manifest, plan), and #10 passed the guard in freeze mode. Reverting would itself rewrite heldout. Lesson: a freeze PR targets `main` directly.

## 2026-11-19: Clean the git history at load time
- Decision: methods see only commits that touch model SQL, with messages replaced by "commit N".
- Alternative: regenerate every split with neutral commits.
- Reason: the saved logs carry the injector's messages and seed-data commits; the rule uses no ground truth, and heldout is frozen so it could not be regenerated anyway.

## 2026-11-19: Two dbt-tests baselines
- Decision: score `dbt_tests` (alert only) and `dbt_tests_guess` (alert plus naive root cause), on the owner's request.
- Alternative: one of them.
- Reason: the first is the honest "what dbt gives you"; the second gives the baseline a fair chance at root cause.

## 2026-11-19: Node-only match is reported as a diagnostic
- Decision: report "right node" at top-1 and top-3 next to the strict location-level numbers, labelled diagnostic.
- Alternative: report only strict numbers.
- Reason: it shows near misses (right model, no commit) without lowering the bar CLAUDE.md sets.

## 2026-11-19: LLM client on the standard library
- Decision: `OpenAICompatibleClient` uses `urllib`, no new dependency; model and URL in faultline.toml.
- Alternative: the `openai` or `httpx` package.
- Reason: one POST endpoint does not justify a dependency; CI only uses a fake client.

## 2026-11-19: Committed no-LLM results must reproduce byte for byte
- Decision: a test reruns `dbt_tests` and `dbt_tests_guess` on dev and compares with `eval/results/dev`.
- Alternative: trust the committed files.
- Reason: "a stranger can reproduce the numbers" is checked on every PR.

## 2026-11-19: Monitors compare with known-good runs from the same split
- Decision: each incident's reference is 9 of the 10 clean runs of its project in the same split (a clean run leaves itself out, a faulted run leaves one out by hash); the harness picks them.
- Alternative: train's clean runs, or every other run of the split.
- Reason: owner's choice; works unchanged on held-out (no train runs of jira), keeps faulted runs out of "normal", and the fixed size reveals nothing.

## 2026-11-19: Monitor fixes are rules, not fitted numbers
- Decision: duplicates only on key columns, freshness lag above 1 hour, distribution band widened by the reference spread. False alarms on dev went from 6/30 to 0/30 with no detection lost.
- Alternative: raise thresholds until the false alarms disappear.
- Reason: each rule names its cause, so it should carry to unseen data; checked once on train (same settings, not used for tuning).

## 2026-11-19: Triage tests run on recorded aggregates in benchmark mode
- Decision: hypothesis tests check the archived profiles, lineage, compiled SQL and git history; live SQL is for real warehouses later.
- Alternative: save each run's DuckDB file and re-query it.
- Reason: owner's approval; the frozen held-out split has no databases, and every profile value was itself an aggregate query.

## 2026-11-19: Data causes only at sources, code causes only at models
- Decision: a model is proposed as a cause only together with a commit that changed its file; data causes are proposed at seeds and sources.
- Alternative: let any anomalous model be a cause on its own.
- Reason: in dbt a model's output changes only if its inputs or its code changed; this keeps "the model is broken" from being a guess without a commit behind it.

## 2026-11-19: The commit that created a file is not a change
- Decision: for each model, the first commit in the cleaned history that touched its file is treated as its creation and never proposed.
- Alternative: propose every commit that touched the file.
- Reason: the initial snapshot touches every file; real history also starts with a creation commit that cannot explain a new incident.

## 2026-11-19: Causes inferred by elimination are reported, marked and ranked last
- Decision: when a model column is off, no commit is on its path and every measured input is normal, its unmeasured (text) inputs are reported as inferred causes.
- Alternative: answer "not confirmed" in that case.
- Reason: output changed with code unchanged means an input changed; the report says it was inferred, and its strength is the lowest, so any observed cause outranks it.

## 2026-11-19: Duplicate rows tested by rows against distinct keys
- Decision: duplicates pass when rows rise above the reference range while the key's distinct count does not.
- Alternative: require distinct < rows, as the M4 duplicates monitor does.
- Reason: the profile's distinct counts are approximate (101 distinct in a 99-row table), so exact uniqueness misses real duplicates.

## 2026-11-19: "Correct not confirmed" is measured against the untested ranking
- Decision: an abstention counts as correct when the same run's best untested cause (no-tests ranking) would have been wrong at top-1.
- Alternative: count every abstention on a faulted run as wrong, or every one as right.
- Reason: owner's approval; it asks whether the gate held back a wrong answer or a right one, from the same evidence.

## 2026-11-19: No-lineage ablation strips the graphs, not the code paths
- Decision: the ablation runs the same triage on a context whose table and column graphs have no edges.
- Alternative: separate code paths that skip each lineage use.
- Reason: one switch removes every use of lineage at once (grouping, proposing upstream, input checks, elimination), and nothing else changes.

## 2026-11-19: The LLM re-ranker may only permute survivors
- Decision: the model returns an order of the numbered survivors; unknown numbers are dropped, missing ones keep their deterministic place, and at most 6 survivors are shown.
- Alternative: let the model return causes in its own words and match them back.
- Reason: CLAUDE.md principle 1: the LLM ranks hypotheses that survived their tests and never invents a cause; a numbered list makes that checkable.

## 2026-11-19: Data faults that change no file are equivalent mutants
- Decision: generation skips a data fault when the workspace has no changed file, and tries the next site.
- Alternative: keep the candidate rule and accept no-op incidents, or exclude constant columns from candidates.
- Reason: owner's choice to fix the generator; this check consumes no randomness, so every incident that was a real fault regenerates identically (dev 78/78, train 125/126).

## 2026-11-19: Train regenerated in full as a new release asset
- Decision: the fixed `inc_stripe_train_019` ships in a regenerated train archive, `benchmark-train-2.tar.gz`, beside the original in release benchmark-v1.
- Alternative: swap the one run into the old archive, or overwrite the old asset.
- Reason: owner's choice; stripe profiles depend on the generation date, so one new run among old ones would raise date alarms; a new name keeps older commits verifiable.

## 2026-11-19: Held-out stays frozen despite the generator fix
- Decision: held-out is not regenerated, scanned or opened; the README and EVAL say it may hold a no-op incident.
- Alternative: let the owner scan it with a counting script.
- Reason: owner's choice; held-out is read only by `faultline eval --split heldout`, once.

## 2026-11-20: Fine-tune both LLM slots, not only the ranker
- Decision: two LoRA adapters, one for triage re-ranking and one for the raw-log baseline, both trained on train only.
- Alternative: ranker only, as the milestone names it.
- Reason: owner's choice; on dev the rules already put the right cause first in every detected run, so a tuned ranker can at best tie, while the raw-log slot has real room.

## 2026-11-20: Base re-run through MLX
- Decision: "base" in M6 is the same 4-bit MLX model the adapters are trained on, served by mlx_lm.server.
- Alternative: compare the tuned MLX model with the Ollama (GGUF) base.
- Reason: owner's approval; base and tuned then differ only by the adapter, not by quantisation format or server.

## 2026-11-20: Raw-log labels say only what the log supports
- Decision: a raw-log training answer names the true cause only when the log shows a failed or errored node, or a commit that changed a model; otherwise "no incident".
- Alternative: always label the true cause.
- Reason: the model sees only the log; teaching it to name causes it cannot see would teach it to guess.

## 2026-11-20: Hosted reference is Claude Opus 5.5 with a hard cap
- Decision: Opus 5.5 in both slots, $3.00 cap checked before each call, free token-count dry run first.
- Alternative: Sonnet 5.5, about half the cost.
- Reason: owner's choice with a balance of about EUR 3; the cap stops the run before it can go over, and the dry run shows the cost first.

## 2026-11-20: Reference rows sit apart from faultline's rows
- Decision: `llm_slots.md` lists local models and the reference in separate tables per slot; the ablation table holds local models only.
- Alternative: one table with a "reference" label column.
- Reason: CLAUDE.md principle 7, never mixed into the local model's tables.

