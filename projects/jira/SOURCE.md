# Source

The held-out project. It appears in no train or dev split; only the owner's one-time held-out generation uses it (see `docs/BENCHMARK.md`). Do not use it while writing rules, prompts or thresholds.

A runnable dbt project around the Fivetran Jira package, built offline on DuckDB.

- Origin: https://github.com/fivetran/dbt_jira
- Commit: 1a9f8b4a4fe76587679330e14fa0decab7fb551c (2026-11-02, package version 1.10.3)
- Licence: Apache License 2.0, copied unchanged in `LICENCE` and in each package folder as `LICENSE`

## What was copied

| Here | From |
|---|---|
| `dbt_project.yml`, `seeds/` | `integration_tests/` of fivetran/dbt_jira at the commit above |
| `packages/jira/` (`models/`, `macros/`, `dbt_project.yml`) | fivetran/dbt_jira at the commit above |
| `packages/fivetran_utils/`, `packages/spark_utils/`, `packages/dbt_utils/` | the same pinned copies as `projects/stripe/` (see its SOURCE.md) |

## What was changed

- `packages.yml` files point to the local folders instead of the dbt package hub, so the build needs no network.
- `profiles.yml` is our own: DuckDB file under `target/`, schema `jira_integration_tests` (where the package expects the source tables), 4 threads.
- Not copied: docs, CI files, the package's own integration consistency tests.

Seed data is the synthetic test data Fivetran ships with the package.
