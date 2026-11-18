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
