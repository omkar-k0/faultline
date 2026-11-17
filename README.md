# faultline

An open-source reliability assistant for dbt Core projects. It detects data incidents, diagnoses the root cause with evidence, and drafts a fix that a human approves. It ships with a public fault-injection benchmark that measures all of this.

How it decides: deterministic lineage and checks first, then statistics, then a local language model that only ranks hypotheses that already passed a query test. If nothing passes, the answer is "not confirmed". No raw rows ever go to a model.

**Status: design stage, no code yet.** The milestones and rules are in [CLAUDE.md](CLAUDE.md). Benchmark numbers will appear here, each linked to a file in `eval/results/`, once they exist.
