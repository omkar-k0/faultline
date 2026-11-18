# Status

Updated 2026-11-18, evening.

## Current milestone

M2 Fault injector + benchmark, issue #7. Plan posted in the draft PR, waiting for approval.

M1 is merged (PR #6, CI green). Its hand-check sheet is not filled in yet.

## Done

- M0: package, dependencies in `uv.lock`, Makefile, CI (`check`, `heldout-guard`), CODEOWNERS, issue templates.
- Test projects: `jaffle_shop` (5 models, 27 columns) and `stripe` (fivetran dbt_stripe with its three packages, 65 models, 1,657 columns), both built offline on DuckDB. A test fails if any model is empty outside a pinned list.
- `collectors/dbt_artifacts.py`: reads manifest v12 and catalog v1; fails loudly on missing files or other versions.
- `lineage/table.py`, `lineage/column.py`: table graph and column lineage for every model column. jaffle_shop 27 of 27 resolved; stripe 1,588 resolved, 69 constant, 0 unresolved. Two undeclared dependencies in stripe are reported.
- `lineage/impact.py`: downstream and upstream for any node or `node.column`, with the path for each hit and the tests on affected columns.
- CLI: `faultline lineage`, `faultline lineage handcheck`, `faultline impact`.
- Hand-check sheet for 30 columns (15 per project): `docs/handcheck/lineage-2026-11-18.md`.
- Tests: 86 passing, including golden lineage for all 27 jaffle_shop columns (checked by hand against the SQL) and a hypothesis property test on random model chains.

## Not verified

- The hand-check sheet is generated but not filled in. Its result is unknown.
- Lineage accuracy on stripe beyond the property tests and spot checks: the hand-check covers 15 stripe columns.
- CODEOWNERS enforcement: needs branch protection on `main` with "Require review from Code Owners", set by the owner.

## Open decisions

- Third test project, held out entirely for the final score. Candidate: tuva-health/demo (Apache 2.0), which needs network access at build time. Decide before M2.

## Broken

- Nothing known.

## Next step

- Owner: approve the M2 plan and answer its open questions; fill in the M1 hand-check sheet; turn on branch protection on `main`.
