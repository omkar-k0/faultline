# Status

Updated 2026-11-18.

## Current milestone

M0 Scaffold, issue #2, draft PR #3.

## Done

- Package skeleton with the layout from CLAUDE.md and `faultline --version`.
- Dependencies pinned in `uv.lock`: dbt-core 1.12, dbt-duckdb, duckdb, sqlglot, networkx; dev: pytest, ruff, mypy, hypothesis.
- `projects/jaffle_shop/` vendored from dbt-labs/jaffle_shop_duckdb (Apache 2.0) with LICENCE and SOURCE.md. Builds on DuckDB: 28 of 28 nodes pass.
- `make setup` and `make check` (ruff, mypy --strict, dbt build, pytest: 32 tests) pass locally and on a fresh clone of the branch.
- CI: `check` and `heldout-guard` jobs. The guard script has 15 tests, including end-to-end runs on a temporary git repo.
- CODEOWNERS, issue templates (milestone, bug, benchmark-fix), DECISIONS.md, ARCHITECTURE.md.

## Not verified

- CI green on GitHub. No workflow run appeared on PR #3 within a few minutes of the push; Actions may need enabling or approving in the repo settings.
- CODEOWNERS enforcement: needs branch protection on `main` with "Require review from Code Owners", set by the owner.

## Open decisions

Candidates for the second and third test projects (licence read, not yet build-tested here):
- fivetran/dbt_stripe: Apache 2.0, 69 models, 31 seed files, DuckDB in its own CI.
- tuva-health/demo: Apache 2.0, synthetic healthcare seeds, DuckDB profile in its own CI; pulls the large the_tuva_project package and terminology data over the network.
- nydasco/dbt_with_duckdb: MIT, 8 models, CSV sources and snapshots, last commit 2024.
- Ruled out: dbt-labs/jaffle-shop, dbt-synthea, mrr-playbook, make-open-data (no licence file); dbt-dummy (Postgres only).

## Broken

- Nothing known.

## Next step

- Owner: review PR #3, turn on branch protection, mark ready when CI is green.
- M1: collectors and lineage. Choose the second and third test projects before M2.
