# faultline

An open-source reliability assistant for dbt Core projects. It detects data incidents, diagnoses the root cause with evidence, and drafts a fix that a human approves. It ships with a public fault-injection benchmark that measures all of this.

How it decides: deterministic lineage and checks first, then statistics, then a local language model that only ranks hypotheses that already passed a query test. If nothing passes, the answer is "not confirmed". No raw rows ever go to a model.

**Status: M7 done. Lineage, the fault-injection benchmark (192 incidents, frozen held-out split), the eval harness, faultline's monitors, a triage agent with its ablations, the local and hosted model comparison, a fix drafter and a test generator are built. Results on dev: [`eval/results/dev/`](eval/results/dev/), including [`fixes.md`](eval/results/dev/fixes.md) and [`testgen.md`](eval/results/dev/testgen.md). Next: M8, the MCP server, reports and the one held-out score.**

## Develop

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
make setup   # create the env, install, build the test projects
make check   # ruff, mypy --strict, dbt build, pytest
```

Test projects live in `projects/`, each with its licence and a `SOURCE.md`.
