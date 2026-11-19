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
