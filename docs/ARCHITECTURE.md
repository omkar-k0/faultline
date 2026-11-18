# Architecture

Not built yet. This file grows one milestone at a time.

## Order of work for every decision

1. Deterministic lineage and checks.
2. Statistics.
3. A local language model, which only ranks hypotheses that already passed a query test and writes the prose.

If no hypothesis passes, the report says "not confirmed".

## Packages

| Package | Job | Milestone |
|---|---|---|
| `collectors` | dbt artefacts, git history, run logs, source freshness | M1 |
| `lineage` | table and column lineage, impact analysis | M1 |
| `inject` | fault injector | M2 |
| `eval` | scorers, baselines, ablations | M3 |
| `monitors` | volume, freshness, null rate, distribution | M4 |
| `incidents` | grouping failures and anomalies into incidents | M5 |
| `triage` | evidence, rules, query tests, ranking, report | M5 |
| `llm` | `LLMClient` interface, local backend, prompts | M5 |
| `fixes` | fix patterns, branch and draft PR | M7 |
| `testgen` | test and fixture proposals, mutation testing | M7 |
| `mcp` | read-only MCP server | M8 |

## Test projects

Vendored under `projects/`, each with its licence and `SOURCE.md`.

- `jaffle_shop`: dbt-labs/jaffle_shop_duckdb, Apache 2.0.
