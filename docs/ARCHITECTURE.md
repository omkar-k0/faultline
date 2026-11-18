# Architecture

This file grows one milestone at a time. Built so far: M0 scaffold, M1 collectors and lineage.

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

## Lineage (M1)

```
target/manifest.json + catalog.json
        |  collectors.dbt_artifacts.load_project
        v
     Project (nodes, columns, compiled SQL, tests)
        |                              |
        | lineage.table                | lineage.column (sqlglot, DuckDB dialect)
        v                              v
  table graph (networkx)        ColumnLineage per model column:
  parent -> child               resolved | constant | unresolved (+ reason)
        \                             |
         \                            v
          ------> lineage.impact <- column graph (networkx)
                  downstream / upstream, shortest path per hit,
                  tests on the affected nodes or columns
```

- Edge kinds: direct, renamed, derived, aggregated.
- Ephemeral models have no catalog entry. Their columns come from their own SQL, and downstream SQL reaches them through the `__dbt__cte__` CTE dbt inlines.
- Relations read by the SQL but missing from `depends_on` are kept and reported as undeclared.
- CLI: `faultline lineage`, `faultline lineage handcheck`, `faultline impact`.

## Test projects

Vendored under `projects/`, each with its licence and `SOURCE.md`.

- `jaffle_shop`: dbt-labs/jaffle_shop_duckdb, Apache 2.0. 5 models, 27 columns.
- `stripe`: fivetran/dbt_stripe with fivetran_utils, spark_utils and dbt_utils, Apache 2.0. 65 models, 1,657 columns.
