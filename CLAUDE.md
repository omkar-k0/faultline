# faultline — project instructions

Open-source reliability assistant for dbt Core projects. It detects data incidents,
diagnoses the root cause with evidence, and drafts a fix for human approval. It ships
with a public fault-injection benchmark that measures all of this.

This is a portfolio project. The repo is judged on two things: the eval numbers in the
README and whether a stranger can reproduce them with one command.

## Principles (do not trade these away)

1. **Confidence gating.** Order of work for every decision: deterministic lineage and
   checks, then statistics, then an LLM. The LLM only ranks hypotheses that survive
   query tests and writes prose. It never invents a cause.
2. **"Not confirmed" is a valid answer.** If no hypothesis passes its query test, the
   report says so. Never pad the ranked list.
3. **Every claim carries evidence.** A hypothesis in a report links to the query, the
   result, and the lineage path that support it.
4. **Humans approve changes.** The fix drafter opens a draft pull request and stops.
   No code path merges, deploys, or writes to a warehouse outside the test projects.
5. **No raw rows to an LLM.** Only metadata, aggregates, masked samples and code.
6. **Local model only at runtime.** All LLM calls go through `faultline.llm.LLMClient`
   and hit a local server. The product never needs a hosted API.
7. **One exception: the reference line.** `faultline eval --reference` runs a hosted
   frontier model in the same two slots as the local model (raw-log baseline and the
   triage ranking step), same prompts, same inputs. It runs on benchmark data only,
   never on a user's project. The key comes from an environment variable and is never
   written to disk, logs or result files. Results are labelled "reference", report
   cost per incident, and are never mixed into the local model's tables.

## Benchmark integrity (the rules that make the numbers worth anything)

- CI enforces this: a `heldout-guard` job fails any PR that changes files under
  `benchmark/heldout/` or adds code under `src/` that references that path.
  `.github/CODEOWNERS` assigns that folder to the human owner.
- `benchmark/heldout/` is frozen after milestone M2. Never read it from `src/`, never
  open it while writing rules, prompts or thresholds, never use it for training data.
- Only `faultline eval --split heldout` may touch it, and only to score.
- Tune on `benchmark/dev/`. Fine-tune only on `benchmark/train/`.
- Splits differ by seed AND by fault location. One whole dbt project is heldout-only.
- Never edit an incident, a ground-truth file or a scorer to make a number go up.
  If ground truth is wrong, fix it in a separate commit titled `benchmark-fix:` and
  re-run every baseline.
- Root cause is scored at location level: node, column where relevant, and commit for
  code faults. Matching the fault type alone does not count.
- Report numbers only from files in `eval/results/`. Never type a metric from memory.

## Stack

- Python 3.12, `uv` for env and lock. Pin versions at setup and commit `uv.lock`.
- dbt Core with the DuckDB adapter first. PostgreSQL adapter after M5.
- `sqlglot` for SQL parsing and column lineage. Do not write a parser.
- `networkx` for the lineage graph. DuckDB file for run history and incidents.
- `pytest`, `ruff`, `mypy --strict` on `src/`.
- Triage agent is a plain explicit state machine. No agent framework.
- Local LLM served through an OpenAI-compatible endpoint (Ollama or similar).
  Model name and URL live in `faultline.toml`, never in code.
- MCP server with the official Python SDK, read-only tools by default.

## Layout

```
src/faultline/
  collectors/     dbt artefacts, git history, run logs, source freshness
  lineage/        table + column lineage, impact analysis
  monitors/       volume, freshness, null rate, distribution
  incidents/      grouping failures and anomalies into incidents
  triage/         evidence, rules, query tests, ranking, report
  fixes/          fix patterns, branch + draft PR
  testgen/        test and fixture proposals, mutation testing
  llm/            LLMClient interface, local backend, prompts
  mcp/            MCP server
  inject/         fault injector
  eval/           scorers, baselines, ablations
benchmark/        train/ dev/ heldout/  (incidents + ground truth)
projects/         vendored open dbt projects, each with LICENCE and source note
eval/results/     JSON + markdown tables written by `faultline eval`
docs/             ARCHITECTURE.md, STATUS.md, DECISIONS.md
tests/
```

## Commands

- `make setup` — create env, install, build the test projects
- `make check` — ruff, mypy, pytest. Must pass before any task is called done.
- `faultline inject --project <p> --fault <type> --seed <n>`
- `faultline eval --split dev|heldout [--baseline <name>] [--ablate <step>]`
- `faultline triage <incident_id>`

## Where work runs

| Work | Where | Why |
|---|---|---|
| Writing code, tests, docs | Claude Code cloud sessions on this GitHub repo | Reviewable branches and PRs |
| `make check` (lint, types, unit tests, dbt build) | GitHub Actions on every PR, and in the session before pushing | Same result for everyone |
| Benchmark generation, dev evals without an LLM | Cloud session or Actions (CPU only) | Fits in 4 vCPU / 16 GB |
| Anything that runs the local LLM, fine-tuning | A machine with a GPU or enough RAM, outside CI | The cloud VM and Actions runners have no GPU |

- CI never calls a real LLM. LLM code is tested with a mocked `LLMClient`.
- LLM eval results produced on another machine come back as a PR that adds files
  under `eval/results/` plus the exact command and config hash that made them.

## GitHub workflow

- Never push to `main`. One branch per milestone or task: `m<N>-<short-name>`.
- Open a draft PR early. The PR description holds the plan, then the "done when"
  checklist from the milestone table with each item ticked or marked not verified.
- A PR is ready only when CI is green. Do not mark it ready yourself; the human does.
- One GitHub issue per milestone, labelled `milestone`. Link the PR with `Closes #n`.
- Large generated artefacts (incident directories, model weights) are not committed.
  Commit the generator, the manifest with content hashes, and ground truth. Publish
  generated incidents as a GitHub Release asset whose hash is in the manifest.
- Never commit secrets. Hosted-model keys live in GitHub Actions secrets or the cloud
  environment's network secrets, never in files.

## How to work in this repo

- Start each session by reading `docs/STATUS.md` and the open milestone issue. End
  each session by updating STATUS.md and pushing: what is done, what is broken, the
  next step. A cloud session can be reclaimed when idle; unpushed work is lost.
- One milestone at a time. Plan first, post the plan in the PR, wait for approval,
  then build.
- Every module ships with tests in the same change. Injector and scorers need
  property tests: an injected fault must be recoverable from its ground-truth file.
- Small commits, one concern each. Conventional prefixes: feat, fix, test, docs,
  eval, benchmark-fix.
- Record every non-obvious choice in `docs/DECISIONS.md` in three lines: decision,
  alternative, reason.
- When something cannot be verified, write "not verified" in STATUS.md. Do not
  describe unbuilt or untested things as working.
- Ask before: adding a dependency, vendoring a project, changing a ground-truth
  schema, or anything that touches `benchmark/heldout/`.
- Vendored dbt projects and public datasets: check the licence first and record it.

## Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Scaffold | `make setup && make check` pass on a clean clone; one dbt project builds on DuckDB; CI green on the PR; `heldout-guard` job, CODEOWNERS and issue templates in place |
| M1 | Collectors + lineage + impact | Table and column lineage for every model; `impact` answers for any node/column; hand-check sheet generated for 30 columns |
| M2 | Fault injector + benchmark | 8 fault types, ~200 incidents plus clean runs across 2-3 projects, ground truth per incident, splits written, heldout frozen |
| M3 | Eval harness + baselines | `faultline eval` writes result tables; "dbt tests only" and "raw-log LLM" baselines scored on dev |
| M4 | Monitors | Detection rate per fault type and false alarms on clean runs reported on dev |
| M5 | Incident manager + triage agent | Top-1 / top-3 / correct "not confirmed" on dev; three ablations run |
| M6 | Self-trained ranker + reference line | Small open model fine-tuned (LoRA) on `benchmark/train/` only; base vs tuned vs hosted reference compared on dev, with cost per incident |
| M7 | Fix drafter + test generator | Fix success rate and mutation score reported |
| M8 | MCP server, reports, release | Read-only MCP tools; post-mortem output; heldout scored once; README carries the tables and a one-command repro |

Fault types: upstream schema change, late or missing source data, duplicate keys,
null spike, distribution shift, model logic bug, broken join, timezone error.

## Definition of done for the project

- `make repro` regenerates every table in the README from a clean clone.
- Heldout was scored once, at the end, and the commit hash is in the README. The
  hosted reference is scored on heldout in that same final run, not before.
- Each README number links to a file in `eval/results/`.
- Known weaknesses are listed in the README, including where the baseline wins.
