# Triage ablations on heldout

Built from the result files in this folder; a row is missing until its run exists.

| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | Correct not confirmed | False alarms | File |
|---|---|---|---|---|---|---|---|
| no LLM ranker (deterministic ranking) | 72.9% (35/48) | 75.0% (36/48) | 6.2% (3/48) | 0.0% (0/48) | n/a | 10.0% (1/10) | [triage.md](triage.md) |
| no tests (every proposed cause ranked) | 20.8% (10/48) | 50.0% (24/48) | 58.3% (28/48) | 0.0% (0/48) | n/a | 10.0% (1/10) | [triage.no_tests.md](triage.no_tests.md) |
| no lineage (causes only at alarmed tables) | 68.8% (33/48) | 70.8% (34/48) | 6.2% (3/48) | 4.2% (2/48) | 100.0% (2/2) | 10.0% (1/10) | [triage.no_lineage.md](triage.no_lineage.md) |
