# Triage ablations on dev

Built from the result files in this folder; a row is missing until its run exists.

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | Correct not confirmed | False alarms | File |
|---|---|---|---|---|---|---|---|
| no LLM ranker (deterministic ranking) | 89.6% (43/48) | 89.6% (43/48) | 0.0% (0/48) | 0.0% (0/48) | n/a | 0.0% (0/30) | [triage.md](triage.md) |
| no tests (every proposed cause ranked) | 39.6% (19/48) | 66.7% (32/48) | 50.0% (24/48) | 0.0% (0/48) | n/a | 0.0% (0/30) | [triage.no_tests.md](triage.no_tests.md) |
| no lineage (causes only at alarmed tables) | 87.5% (42/48) | 87.5% (42/48) | 0.0% (0/48) | 2.1% (1/48) | 100.0% (1/1) | 0.0% (0/30) | [triage.no_lineage.md](triage.no_lineage.md) |
