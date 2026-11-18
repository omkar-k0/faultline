# Source

A runnable dbt project around the Fivetran Stripe package, built offline on DuckDB.

- Origin: https://github.com/fivetran/dbt_stripe
- Commit: 7f5d6ae0d474b72b10ed765b7062725f1e5771b1 (2026-10-28, package version 1.10.2)
- Licence: Apache License 2.0, copied unchanged in `LICENCE` and in each package folder as `LICENSE`

## What was copied

| Here | From |
|---|---|
| `dbt_project.yml`, `seeds/` | `integration_tests/` of fivetran/dbt_stripe at the commit above |
| `packages/stripe/` (`models/`, `macros/`, `dbt_project.yml`) | fivetran/dbt_stripe at the commit above |
| `packages/fivetran_utils/` (`macros/`, `dbt_project.yml`) | https://github.com/fivetran/dbt_fivetran_utils, tag v0.4.14, commit 81263d6314a6a65b0b437e02ef06328236ba97e7, Apache 2.0 |
| `packages/spark_utils/` (`macros/`, `dbt_project.yml`) | https://github.com/dbt-labs/spark-utils, tag 0.3.5, commit 34ac5cb23d77064c5194aab26dbdaba9bb26c113, Apache 2.0 |
| `packages/dbt_utils/` (`macros/`, `dbt_project.yml`) | https://github.com/dbt-labs/dbt-utils, tag 1.4.1, commit 49b932cb1f6fd0f7dfbf9048512db6415f570b20, Apache 2.0 |

## What was changed

- `packages.yml` files point to the local folders above instead of the dbt package hub, so the build needs no network and every package is pinned.
- `profiles.yml` is our own: DuckDB file under `target/`, schema `stripe_integrations_tests` (where the package expects the source tables), 4 threads.
- Build order: `dbt seed` runs before `dbt build`. The staging models read sources, not seeds, so dbt cannot order them; without the extra seed step every staging table is silently empty.
- Not copied: docs, images, CI files, the packages' own integration tests.

Seed data is the synthetic test data Fivetran ships with the package. Two reporting models stay empty with this data: `stripe__ending_balance_reconciliation_itemized_4` and `stripe__payout_itemized_3`.
