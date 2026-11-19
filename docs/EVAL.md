# Evaluation

`faultline eval --split <train|dev> --baseline <name>` runs a method on every incident of a split, scores it against ground truth, and writes `eval/results/<split>/<baseline>.json` (every prediction, outcome and the config) and `.md` (the table). A `.run.json` next to them records the commit and time of the run.

The held-out split cannot be evaluated yet: it is scored once, at the end (M8).

## What a method sees

Only what an engineer would have after a run, loaded from the published archive (hash-checked against `benchmark/manifest.json`):

- dbt's `run_results.json`, `manifest.json`, `catalog.json` and `dbt.log`
- an aggregate profile of every table (no rows)
- a **cleaned git history**

Ground truth (`truth.json`) is read by the scorer only. The loader refuses a run directory that contains it.

### Why the history is cleaned

The injector committed every fault in the workspace's git repository, so the saved log carries its own messages (`inject: …`) and commits for seed-data changes, which real history never has. The loader keeps only commits that touch model SQL and renames every message to `commit N`. The rule never looks at ground truth. A test checks every dev run for leaked injector strings.

## How a root cause is scored

A predicted location matches the truth when:

1. its node is the truth's node, or the physical node the change was written to (for stripe, models read a source whose data sits in a seed: the same relation);
2. its column equals the truth's column, when the truth names one;
3. for code faults, its commit matches the truth's commit (a prefix of at least 7 characters).

Matching the fault type alone never counts.

## Metrics

For faulted runs, per fault type, per project and overall:

| Metric | Meaning |
|---|---|
| Detected | the method flagged an incident |
| Top-1 | the first candidate matches |
| Top-3 | one of the first three matches |
| Wrong top-1 | a first candidate was given and it is wrong: a confident wrong answer |
| Not confirmed | flagged, but no cause named: an honest "I don't know" |

For clean runs: **false alarms**, the share flagged as incidents.

Wrong and not-confirmed are kept apart on purpose: faultline's design says a wrong answer is worse than no answer.

**Diagnostic, not a score:** "right node" at top-1 and top-3 ignores column and commit. It shows near misses (for example the right model without the commit) and never replaces the strict numbers.

## Baselines

| Name | LLM | What it does |
|---|---|---|
| `dbt_tests` | no | Alert only: flags a run when the build died or any dbt test failed or warned. Names no cause. |
| `dbt_tests_guess` | no | Same alert, plus a naive cause: the nodes and columns of failing tests, then nodes that errored, upstream first. It has no notion of commits. |
| `raw_log_llm` | local | The trimmed dbt log, the results that did not succeed, the cleaned history and the list of node ids go to a local model, which answers in strict JSON (incident yes/no, up to 3 locations or "not confirmed"). Unreadable answers count as not confirmed. Temperature 0, fixed seed; model name and prompt hash are in the result file. |

`make eval-dev` runs the two no-LLM baselines. Their result files are reproducible byte for byte, and a test fails if the committed files go stale.

## Monitors (M4)

`monitors` is faultline's own detection step, scored like a baseline: `faultline eval --split dev --baseline monitors`. It compares each run's table profile with **known-good history**, the other clean runs of the same project in the same split.

- Every incident is compared with exactly 9 of the 10 clean runs. A clean run never sees itself; a faulted run leaves one out by a hash of its id. The reference size therefore says nothing about the incident.
- The harness picks the references from ground truth; the monitors themselves never read it.
- A value is unusual when it leaves the range of the reference runs widened by a margin (settings in `faultline.toml` under `[monitors]`).

| Monitor | Flags when |
|---|---|
| schema | a relation or column disappears or appears, or a column type changes |
| volume | row count leaves the reference range by more than 1% (at least 1 row) |
| freshness | the newest value of a time column falls more than 1 hour behind the reference, or the column goes empty |
| null rate | a column's null share rises more than 2 points above the reference maximum |
| distribution | a numeric mean, median, min or max leaves the reference range widened by the largest of 10% of the median, 6 MADs and the reference spread |
| duplicates | a key column (`id` or `*_id`) that is unique in every reference run stops being unique |
| time shift | a time column's min and max both move by the same amount |

Anomalies also give candidate locations (most upstream first, then most severe). Strict root cause is M5's job; the numbers are reported because the harness scores every method the same way.

### How the settings were chosen

Tuned on dev only. The first version raised 6 false alarms on 30 clean dev runs. Three changes, each a rule rather than a fitted number, brought that to 0 without losing a detection:

1. Duplicates only on key columns: 2% noise sometimes made two amounts equal.
2. Freshness needs a lag over 1 hour: the noise also nudged a court's UTC offset column (330 to 331 minutes), so clean hearing times moved by a minute.
3. The distribution band also widens by the reference spread: a fee column whose median sits between -1 and 1.

The same settings were then run once on train, which played no part in tuning; the result is in `eval/results/train/monitors.md`. Held-out remains the honest number.

## Triage (M5a)

`triage` is faultline's diagnosis: `faultline eval --split dev --baseline triage`, or `faultline triage <run id>` for one run (prints the report and stores its incidents in `build/faultline.duckdb`). It is a plain state machine, `gather -> group -> propose -> test -> rank -> report`, with no language model.

1. **Gather.** Symptoms of the run: the monitor anomalies (same references as M4) plus failed dbt tests and errored models. Nodes dbt skipped are consequences, not symptoms.
2. **Group.** Symptoms joined by table lineage into incidents: ten alarms below one broken source are one incident.
3. **Propose.** A table changes for two reasons only: its inputs changed or its code changed. Data causes are proposed at seeds and sources upstream of a symptom (a column, the table, or duplicate rows on a key column). Code causes are proposed at models on the path, one per commit that changed the model's file; the commit that created a file does not count.
4. **Test.** Each candidate is tested on the run's evidence:

| Candidate | Passes when |
|---|---|
| source column | that column itself shows a symptom |
| source table | the table itself shows a table-level symptom (rows, missing relation) |
| duplicate rows on key `k` | `k` is a key by name, unique in every reference run, rows rose above the reference range, and the distinct count of `k` did not rise with them |
| code change in model `M`, commit `c` | `c` changed `M`'s file; `M` (or the named column) is off; every input table of `M` is normal (and, for a column, every input column) |

   Then **elimination**: a model column that no tested cause explains, with no commit on its path and every measured input normal, must have changed through an input the profile cannot measure (text columns carry no distribution statistics). Those inputs are reported as causes **inferred by elimination**, marked as such and ranked below every observed cause.
5. **Rank.** Survivors only: strongest evidence first (structural before statistical), a named column before a whole table, then the number of symptoms explained. The list is never padded. With symptoms but no survivor, the answer is "not confirmed".
6. **Report.** Up to three causes per incident, each with its checks, the symptoms it explains and the lineage path to each.

**What the tests run against.** The benchmark archives hold each table's aggregate profile (every number was produced by an aggregate SQL query when the run was captured), not the databases. So in benchmark mode the tests check those recorded aggregates plus lineage, compiled SQL and git history. Against a live warehouse the same tests would run as SQL. Saving the databases instead is not possible for the frozen held-out split.

**How it was built.** Designed and tuned on dev only, by reading where monitors went wrong there. Then run once on train with the same code, as a check; train played no part in tuning. Results: `eval/results/dev/triage.md`, `eval/results/train/triage.md`.

## Triage ablations and the gate (M5b)

Three ablations, each run through the same harness. The table is built from the result files: `eval/results/dev/ablations.md`.

| Variant | Command | What is switched off |
|---|---|---|
| full | `faultline eval --split dev --baseline triage_llm` | nothing: tests, lineage, and the local LLM re-ranker (runs on your machine, see below) |
| no LLM ranker | `faultline eval --split dev --baseline triage` | the re-ranker; survivors keep the deterministic order |
| no tests | `... --baseline triage --ablate tests` | the tests and elimination; every proposed cause is ranked by the same ranking |
| no lineage | `... --baseline triage --ablate lineage` | every lineage edge: incidents are single tables, causes are proposed only at alarmed tables, and checks on inputs have nothing to check |

**The gate** is reported for every triage variant (section "The gate" in its `.md`):
- *Answered* and *right when answering*: of the detected faulted runs where triage named a cause, how often its top-1 was right.
- *Correct not confirmed*: triage abstained, and its best untested cause (the no-tests ranking of the same run) would have been wrong at top-1. An abstention that hid a right answer counts against it.
- *Without the tests*: top-1 of the untested ranking, computed on the same run.

### Running the LLM re-ranker on your own machine

The re-ranker sees each incident's symptoms and the causes that passed their tests, with checks and lineage. It answers with an order and a two-line summary. It cannot add a cause: indices that do not exist are dropped, and any cause it leaves out keeps its deterministic place after the ones it ordered. An unusable answer leaves the deterministic order. Prompt: `src/faultline/triage/llm_rank.py`; its hash is in the result file.

1. Start the model server as for `raw_log_llm` (below): `OLLAMA_CONTEXT_LENGTH=16384 ollama serve`, with `qwen2.5:7b-instruct` pulled.
2. In a second terminal:
   ```
   cd faultline
   git fetch && git switch m5b-ablations && git pull
   make setup
   make eval-dev-triage-llm
   ```
   One prompt per incident that has causes (about 45 on dev), each much shorter than the `raw_log_llm` prompts.
3. Commit the files it writes, `eval/results/dev/triage_llm.{json,md,run.json}` and the updated `eval/results/dev/ablations.md`, and push to the branch.

## Running `raw_log_llm` on your own machine

CI never calls a model. This baseline runs on a machine with enough memory (16 GB is enough for a 7B model) and comes back as a pull request.

1. Install Ollama (https://ollama.com/download, or `brew install ollama`).
2. Quit the Ollama app if it is running, then start the server with a context long enough for the prompts (up to about 10,000 tokens):
   ```
   OLLAMA_CONTEXT_LENGTH=16384 ollama serve
   ```
3. In a second terminal:
   ```
   ollama pull qwen2.5:7b-instruct
   cd faultline
   git switch m3-eval && git pull
   make setup
   make eval-dev-llm
   ```
   `faultline.toml` already points at `http://localhost:11434/v1` and `qwen2.5:7b-instruct`. The run sends 78 prompts; expect one to two hours on a MacBook Air. Keep it plugged in.
4. Commit the three files it writes, `eval/results/dev/raw_log_llm.{json,md,run.json}`, on a branch and open a PR. The JSON carries the command, config hash, model and prompt hash.

## Known weaknesses

- **Naming the commit is easy.** In every code-fault run the fault is the only commit after the clean snapshot. A method that always names the newest commit gets the commit part right for free.
- **`dbt_tests_guess` has a structural ceiling.** dbt tests sit on staging and mart models, while data faults sit in sources, so its guesses land one step downstream.
- **Clean runs do not vary in volume** (see BENCHMARK.md), so false alarms on row counts are an easy test.
- **Category-mix shifts are nearly invisible to monitors.** The profile stores distinct counts, not category frequencies.
- **The injector's noise touched a non-measure number** (a court's UTC offset in minutes). It is frozen into the benchmark now; the freshness tolerance absorbs it.
- **"Not confirmed" never fired on dev or train.** Every detected faulted run got at least one surviving cause, so "correct not confirmed" has no cases yet (n/a). What the tests filter out shows in the no-tests ablation instead.
- **Lineage adds little on this benchmark.** Every seed and source is profiled, so most data faults show a symptom at the source itself and are found without walking upstream. Lineage matters where the source cannot show the change (a text column), the one dev case the no-lineage ablation loses. A real project with unprofiled sources would lean on it more.
- **Triage was shaped by dev's misses.** Train is the check; held-out remains the honest number.
- **Elimination leans on what the profile cannot see.** It names text inputs because they have no distribution statistics; a change hidden inside a measured column's summary would point it the wrong way.
- **A code cause can appear more than once in a report**, with the same commit and different columns.
- **Held-out may contain a fault that changes nothing.** Train had one (fixed, see BENCHMARK.md). Held-out was frozen before the generator fix and is not opened, so it is checked only after its final score.

