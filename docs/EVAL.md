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
