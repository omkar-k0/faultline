# faultline

An open-source reliability assistant for dbt Core projects. It detects data incidents, finds the root cause with evidence, drafts a fix for a human to approve, and proposes the tests that would have caught it. It ships with a public fault-injection benchmark that measures all of this, and a one-command check of every number below.

**Status: built and measured. Methods were shaped on dev; the frozen held-out project (jira) was scored once, on 23 Nov 2026, and is the honest number. Triage falls from 89.6% top-1 on dev to 72.9% on held-out.**

## How it decides

Confidence gating, in a fixed order:

1. **Deterministic first.** Monitors compare each table with known-good runs; dbt's own test results count too. Symptoms are grouped into incidents through table lineage.
2. **Every candidate cause is tested.** A table changes only if its inputs or its code changed, so data causes are proposed at sources and code causes at models, each with the commit that changed it. Each candidate must pass a test against the run's evidence (profiles, lineage, compiled SQL, git history). A cause no test can confirm is dropped.
3. **"Not confirmed" is an answer.** If nothing survives, faultline says so instead of guessing.
4. **A language model is optional and boxed in.** A local model may re-order the survivors and write a summary; it can never add a cause. No raw rows ever reach a model.
5. **Humans approve changes.** Fixes open as draft pull requests and stop there.

## Results

Each number links to the result file it comes from. `make repro` checks all of them.

<!-- results:start (written by `faultline readme`; do not edit by hand) -->

### Finding the root cause

Top-1: the first named cause is the right node (and column and commit, where the fault has one). Wrong top-1: a confident wrong answer. False alarms: clean runs flagged.

| Method | Split | Detected | Top-1 | Top-3 | Wrong top-1 | False alarms |
|---|---|---|---|---|---|---|
| dbt's own tests (alert only) | dev | [22.9% (11/48)](eval/results/dev/dbt_tests.md) | [0.0% (0/48)](eval/results/dev/dbt_tests.md) | [0.0% (0/48)](eval/results/dev/dbt_tests.md) | [0.0% (0/48)](eval/results/dev/dbt_tests.md) | [0.0% (0/30)](eval/results/dev/dbt_tests.md) |
| dbt tests + simple root-cause guess | dev | [22.9% (11/48)](eval/results/dev/dbt_tests_guess.md) | [0.0% (0/48)](eval/results/dev/dbt_tests_guess.md) | [0.0% (0/48)](eval/results/dev/dbt_tests_guess.md) | [22.9% (11/48)](eval/results/dev/dbt_tests_guess.md) | [0.0% (0/30)](eval/results/dev/dbt_tests_guess.md) |
| local 7B model reading the raw log | dev | [14.6% (7/48)](eval/results/dev/raw_log_llm.mlx_base.md) | [2.1% (1/48)](eval/results/dev/raw_log_llm.mlx_base.md) | [2.1% (1/48)](eval/results/dev/raw_log_llm.mlx_base.md) | [12.5% (6/48)](eval/results/dev/raw_log_llm.mlx_base.md) | [0.0% (0/30)](eval/results/dev/raw_log_llm.mlx_base.md) |
| faultline monitors (M4) | dev | [89.6% (43/48)](eval/results/dev/monitors.md) | [56.2% (27/48)](eval/results/dev/monitors.md) | [56.2% (27/48)](eval/results/dev/monitors.md) | [33.3% (16/48)](eval/results/dev/monitors.md) | [0.0% (0/30)](eval/results/dev/monitors.md) |
| **faultline triage (M5)** | dev | [89.6% (43/48)](eval/results/dev/triage.md) | [89.6% (43/48)](eval/results/dev/triage.md) | [89.6% (43/48)](eval/results/dev/triage.md) | [0.0% (0/48)](eval/results/dev/triage.md) | [0.0% (0/30)](eval/results/dev/triage.md) |
| dbt's own tests (alert only) | held-out (jira, scored once) | [10.4% (5/48)](eval/results/heldout/dbt_tests.md) | [0.0% (0/48)](eval/results/heldout/dbt_tests.md) | [0.0% (0/48)](eval/results/heldout/dbt_tests.md) | [0.0% (0/48)](eval/results/heldout/dbt_tests.md) | [0.0% (0/10)](eval/results/heldout/dbt_tests.md) |
| dbt tests + simple root-cause guess | held-out (jira, scored once) | [10.4% (5/48)](eval/results/heldout/dbt_tests_guess.md) | [0.0% (0/48)](eval/results/heldout/dbt_tests_guess.md) | [0.0% (0/48)](eval/results/heldout/dbt_tests_guess.md) | [10.4% (5/48)](eval/results/heldout/dbt_tests_guess.md) | [0.0% (0/10)](eval/results/heldout/dbt_tests_guess.md) |
| local 7B model reading the raw log | held-out (jira, scored once) | [10.4% (5/48)](eval/results/heldout/raw_log_llm.mlx_base.md) | [0.0% (0/48)](eval/results/heldout/raw_log_llm.mlx_base.md) | [2.1% (1/48)](eval/results/heldout/raw_log_llm.mlx_base.md) | [10.4% (5/48)](eval/results/heldout/raw_log_llm.mlx_base.md) | [0.0% (0/10)](eval/results/heldout/raw_log_llm.mlx_base.md) |
| faultline monitors (M4) | held-out (jira, scored once) | [79.2% (38/48)](eval/results/heldout/monitors.md) | [54.2% (26/48)](eval/results/heldout/monitors.md) | [56.2% (27/48)](eval/results/heldout/monitors.md) | [25.0% (12/48)](eval/results/heldout/monitors.md) | [10.0% (1/10)](eval/results/heldout/monitors.md) |
| **faultline triage (M5)** | held-out (jira, scored once) | [79.2% (38/48)](eval/results/heldout/triage.md) | [72.9% (35/48)](eval/results/heldout/triage.md) | [75.0% (36/48)](eval/results/heldout/triage.md) | [6.2% (3/48)](eval/results/heldout/triage.md) | [10.0% (1/10)](eval/results/heldout/triage.md) |

### What each part of triage is worth

| Variant | Split | Top-1 | Wrong top-1 |
|---|---|---|---|
| full deterministic triage | dev | [89.6% (43/48)](eval/results/dev/triage.md) | [0.0% (0/48)](eval/results/dev/triage.md) |
| without the tests | dev | [39.6% (19/48)](eval/results/dev/triage.no_tests.md) | [50.0% (24/48)](eval/results/dev/triage.no_tests.md) |
| without lineage | dev | [87.5% (42/48)](eval/results/dev/triage.no_lineage.md) | [0.0% (0/48)](eval/results/dev/triage.no_lineage.md) |
| full deterministic triage | held-out (jira, scored once) | [72.9% (35/48)](eval/results/heldout/triage.md) | [6.2% (3/48)](eval/results/heldout/triage.md) |
| without the tests | held-out (jira, scored once) | [20.8% (10/48)](eval/results/heldout/triage.no_tests.md) | [58.3% (28/48)](eval/results/heldout/triage.no_tests.md) |
| without lineage | held-out (jira, scored once) | [68.8% (33/48)](eval/results/heldout/triage.no_lineage.md) | [6.2% (3/48)](eval/results/heldout/triage.no_lineage.md) |

### Language models in faultline's two model slots

faultline, with a local model or none:

| Slot | Model | Split | Top-1 | Wrong top-1 | Cost per incident |
|---|---|---|---|---|---|
| ranking | rules only | dev | [89.6% (43/48)](eval/results/dev/triage.md) | [0.0% (0/48)](eval/results/dev/triage.md) | local |
| ranking | local 7B, base | dev | [87.5% (42/48)](eval/results/dev/triage_llm.mlx_base.md) | [2.1% (1/48)](eval/results/dev/triage_llm.mlx_base.md) | local |
| ranking | local 7B, fine-tuned on train | dev | [89.6% (43/48)](eval/results/dev/triage_llm.mlx_ranker.md) | [0.0% (0/48)](eval/results/dev/triage_llm.mlx_ranker.md) | local |
| raw log | local 7B, base | dev | [2.1% (1/48)](eval/results/dev/raw_log_llm.mlx_base.md) | [12.5% (6/48)](eval/results/dev/raw_log_llm.mlx_base.md) | local |
| raw log | local 7B, fine-tuned on train | dev | [4.2% (2/48)](eval/results/dev/raw_log_llm.mlx_raw_log.md) | [18.8% (9/48)](eval/results/dev/raw_log_llm.mlx_raw_log.md) | local |
| ranking | rules only | held-out (jira, scored once) | [72.9% (35/48)](eval/results/heldout/triage.md) | [6.2% (3/48)](eval/results/heldout/triage.md) | local |
| ranking | local 7B, base | held-out (jira, scored once) | [70.8% (34/48)](eval/results/heldout/triage_llm.mlx_base.md) | [8.3% (4/48)](eval/results/heldout/triage_llm.mlx_base.md) | local |
| ranking | local 7B, fine-tuned on train | held-out (jira, scored once) | [75.0% (36/48)](eval/results/heldout/triage_llm.mlx_ranker.md) | [4.2% (2/48)](eval/results/heldout/triage_llm.mlx_ranker.md) | local |
| raw log | local 7B, base | held-out (jira, scored once) | [0.0% (0/48)](eval/results/heldout/raw_log_llm.mlx_base.md) | [10.4% (5/48)](eval/results/heldout/raw_log_llm.mlx_base.md) | local |
| raw log | local 7B, fine-tuned on train | held-out (jira, scored once) | [2.1% (1/48)](eval/results/heldout/raw_log_llm.mlx_raw_log.md) | [37.5% (18/48)](eval/results/heldout/raw_log_llm.mlx_raw_log.md) | local |

Reference line, a hosted model that is not part of faultline (CLAUDE.md principle 7):

| Slot | Model | Split | Top-1 | Wrong top-1 | Cost per incident |
|---|---|---|---|---|---|
| ranking | Claude Opus 5.5 (hosted reference) | dev | [87.5% (42/48)](eval/results/dev/triage_llm.reference.md) | [2.1% (1/48)](eval/results/dev/triage_llm.reference.md) | [$0.0057](eval/results/dev/triage_llm.reference.md) |
| raw log | Claude Opus 5.5 (hosted reference) | dev | [31.2% (15/48)](eval/results/dev/raw_log_llm.reference.md) | [0.0% (0/48)](eval/results/dev/raw_log_llm.reference.md) | [$0.0408](eval/results/dev/raw_log_llm.reference.md) |
| ranking | Claude Opus 5.5 (hosted reference) | held-out (jira, scored once) | [72.9% (35/48)](eval/results/heldout/triage_llm.reference.md) | [6.2% (3/48)](eval/results/heldout/triage_llm.reference.md) | [$0.0084](eval/results/heldout/triage_llm.reference.md) |
| raw log | Claude Opus 5.5 (hosted reference) | held-out (jira, scored once) | [8.3% (4/48)](eval/results/heldout/raw_log_llm.reference.md) | [4.2% (2/48)](eval/results/heldout/raw_log_llm.reference.md) | [$0.0515](eval/results/heldout/raw_log_llm.reference.md) |

### Fixes and generated tests

| What | Split | Result | False alarms on clean runs |
|---|---|---|---|
| fix drafter: faults fixed (build passes, every model back to normal) | dev | [33.3% (16/48)](eval/results/dev/fixes.md) | [0.0% (0/30)](eval/results/dev/fixes.md) fixes proposed |
| generated tests: faults caught (mutation score) | dev | [79.2% (38/48)](eval/results/dev/testgen.md) vs the projects' own tests [14.6% (7/48)](eval/results/dev/testgen.md) | [3.3% (1/30)](eval/results/dev/testgen.md) |

Held-out was scored once per method, at commits `d1155977ebd4` and `edb4a0cdea7d`; each result's `.run.json` names its commit (see docs/EVAL.md).

<!-- results:end -->

## Known weaknesses

From [`docs/EVAL.md`](docs/EVAL.md), where each one is explained.

- **Held-out is clearly harder than dev.** Triage top-1 falls from 43/48 to 35/48. Ten faults were not detected at all: 5 of 6 distribution shifts, 3 of 6 model logic bugs, 2 of 6 broken joins. Three late-or-missing-data runs got a wrong top cause, and one of 10 clean runs raised a false alarm.
- **On held-out the model slots do not beat the rules either:** the tuned ranker gains one incident (36/48 vs 35/48), the base model loses one, and Claude ties the rules. In the raw-log slot the best is Claude at 4/48 (it dropped from 15/48 on dev), and the tuned local model names a wrong cause in 18 of 48 runs.
- **Naming the commit is easy in this benchmark:** a code fault is the only commit after the clean snapshot.
- **The model slots add little.** A tuned local ranker ties the rules on dev; a hosted model reads raw logs far better than local ones and still trails triage by a wide margin.
- **Fine-tuning the raw-log model made it more confident, not more precise** (more confidently wrong answers than the base model).
- **Lineage adds little here,** because every source in the benchmark is profiled; it matters where a source cannot show the change.
- **"Not confirmed" never fired on dev or train,** so abstention is barely tested.
- **Triage is scored on where, not on what:** two duplicate-key runs got the right place but not the right kind of cause, so no fix was drafted.
- **Most data faults get no code fix, by design,** which keeps the fix rate low and honest.
- **Generated tests miss most model logic bugs** and half the time shifts, and one check misfires on a postal code.
- **Triage and the test generator were shaped on dev.** Train was the check for triage; held-out is the honest number, and the gap above is the cost of that.
- **The benchmark is synthetic** (injected faults, one fully synthetic project, court_cases), and held-out may contain a fault that changes nothing (see [`docs/BENCHMARK.md`](docs/BENCHMARK.md)).

## Use it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
make setup                                   # environment, dependencies, the test dbt projects
faultline triage inc_jaffle_shop_dev_014     # one benchmark run: causes and evidence
faultline postmortem inc_jaffle_shop_dev_014 # a written post-mortem in build/postmortems/
faultline fix draft inc_jaffle_shop_dev_014  # the drafted fix as a patch and PR text
faultline mcp                                # read-only tools for an assistant (stdio)
```

To give Claude Desktop or Claude Code read-only access, add an MCP server that runs `uv run --directory <path to faultline> faultline mcp`. It offers `list_incidents`, `get_report`, `get_lineage`, `impact_of` and `get_results`; none of them changes anything. Which dbt project it reads is set in `faultline.toml` under `[mcp]`.

## Reproduce

```
make repro
```

From a clean clone this sets up, downloads the benchmark archives (hash-checked against `benchmark/manifest.json`), then:
- re-runs every result that needs no model and compares it byte for byte;
- re-scores the stored answers of every model run against the ground truth (the models themselves are not needed);
- re-summarises the fix and generated-test results from their stored runs;
- checks the tables above against the files.

Re-running the model results needs the models: a local server (see `docs/EVAL.md`) and, for the reference line, an Anthropic API key. Re-running fixes and generated tests in full takes about 160 dbt builds: `make eval-dev-fixes eval-dev-testgen`.

## Develop

```
make check   # ruff, mypy --strict, dbt build, pytest
```

Plans and decisions: [`docs/STATUS.md`](docs/STATUS.md), [`docs/DECISIONS.md`](docs/DECISIONS.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The benchmark: [`docs/BENCHMARK.md`](docs/BENCHMARK.md). How it is scored: [`docs/EVAL.md`](docs/EVAL.md).

Test projects live in `projects/`, each with its licence and a `SOURCE.md`: dbt-labs jaffle_shop, Fivetran's stripe and jira packages, and a synthetic court-case project generated here. Licence: see `LICENSE`.
