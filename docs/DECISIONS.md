# Decisions

Each entry: decision, alternative, reason.

## 2026-11-18: First test project is jaffle_shop_duckdb
- Decision: vendor dbt-labs/jaffle_shop_duckdb at a pinned commit into `projects/jaffle_shop/`.
- Alternative: write a toy project ourselves.
- Reason: a well-known open project (Apache 2.0) makes results credible and builds on DuckDB in seconds.

## 2026-11-18: Stay on dbt Core v1
- Decision: pin `dbt-core>=1.11,<2`.
- Alternative: dbt v2, which dbt now announces as the default for new installs.
- Reason: the vendored projects target v1, and the artefact formats faultline reads are documented for v1. Revisit after M2.

## 2026-11-18: Full stack added at M0
- Decision: add `sqlglot`, `networkx` and `hypothesis` now, with dbt and the dev tools.
- Alternative: add each when first used.
- Reason: owner's choice, so `uv.lock` is settled before M1.

## 2026-11-18: heldout-guard uses one allowlisted file
- Decision: any added `src/` line matching "heldout" (also "held_out", "held-out") fails, except in `src/faultline/eval/splits.py`.
- Alternative: block every mention in `src/`.
- Reason: `faultline eval --split heldout` must name the split somewhere. One owner-reviewed file keeps that in a single place.

## 2026-11-18: The guard and CI files are owner-reviewed
- Decision: CODEOWNERS covers `benchmark/heldout/`, the guard script, the workflows and CODEOWNERS itself.
- Alternative: cover only `benchmark/heldout/`.
- Reason: otherwise a PR could weaken the guard and touch heldout in the same change.

## 2026-11-18: CLI uses argparse
- Decision: plain `argparse`.
- Alternative: typer or click.
- Reason: no extra dependency for a handful of subcommands.

## 2026-11-18: Second test project is fivetran dbt_stripe, with its packages vendored
- Decision: vendor dbt_stripe plus fivetran_utils, spark_utils and dbt_utils as local packages.
- Alternative: let `dbt deps` fetch them from the dbt package hub.
- Reason: the build then needs no network and every package is pinned; the hub is unreachable from the cloud session.

## 2026-11-18: Seed before build, and test that models hold rows
- Decision: `make build-projects` runs `dbt seed` before `dbt build`, and a test fails if any model is empty outside a pinned list.
- Alternative: trust a green `dbt build`.
- Reason: the first stripe build passed 105 of 105 with every staging table empty, because dbt read the sources before the seeds loaded.

## 2026-11-18: Column lineage tracks value flow, one dbt hop per edge
- Decision: edges come from sqlglot projection lineage on compiled SQL. Join keys, WHERE and GROUP BY columns are not edges. Each edge goes one dbt model back; longer chains come from the graph.
- Alternative: also record filter and join columns as edges.
- Reason: impact and root cause first need where values come from. Join keys matter for broken-join faults and get their own edge type when M5 needs them.

## 2026-11-18: Lineage follows the SQL, not dbt's depends_on
- Decision: when compiled SQL reads a relation missing from `depends_on`, keep the edge and report it as undeclared.
- Alternative: drop edges dbt did not declare.
- Reason: the SQL is what runs. dbt_stripe has two such models; hiding them would hide a real source of incidents.

## 2026-11-18: One sqlglot pass per model
- Decision: call `sqlglot.lineage` once per model for all columns, falling back to one column at a time only if that fails.
- Alternative: one call per column.
- Reason: stripe lineage went from 31 s to 7 s with the same result.
