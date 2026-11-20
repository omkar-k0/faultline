# faultline

An open-source reliability assistant for dbt Core projects. It detects data incidents, diagnoses the root cause with evidence, and drafts a fix that a human approves. It ships with a public fault-injection benchmark that measures all of this.

How it decides: deterministic lineage and checks first, then statistics, then a local language model that only ranks hypotheses that already passed a query test. If nothing passes, the answer is "not confirmed". No raw rows ever go to a model.

**Status: M5 done, M6 in progress. Lineage, the fault-injection benchmark (192 incidents, frozen held-out split), the eval harness with three baselines, faultline's monitors, and a triage agent with its ablations (including an optional local-LLM re-ranker) are built. Results on dev are in [`eval/results/dev/`](eval/results/dev/), the ablations in [`eval/results/dev/ablations.md`](eval/results/dev/ablations.md). M6 (a fine-tuned local model and a hosted reference line) is being built; its table is [`eval/results/dev/llm_slots.md`](eval/results/dev/llm_slots.md).**

## Develop

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/).

```
make setup   # create the env, install, build the test projects
make check   # ruff, mypy --strict, dbt build, pytest
```

Test projects live in `projects/`, each with its licence and a `SOURCE.md`.
