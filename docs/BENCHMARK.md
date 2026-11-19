# Benchmark

faultline is scored on incidents we create on purpose: a copy of a test project, one injected fault (or none, for a clean run), a dbt run, and a ground-truth file that says what was injected and where.

## How an incident is made

1. Copy the vendored project (`projects/<name>`) into a temporary workspace. The vendored project is never changed.
2. Add natural variation: numeric measures in the seed data get 2% multiplicative noise. Keys, dates, timestamps, booleans and text stay as shipped, and rows are never dropped (dropping payments left orders without a payment and failed `not_null` tests on clean runs).
3. Commit the clean state in the workspace's own git repository, with a fixed author and date so hashes are reproducible.
4. Inject one fault (see below). Code faults are committed, and their commit hash goes into the ground truth.
5. Run `dbt deps`, `dbt seed`, `dbt build` and `dbt docs generate` in one process.
6. Save the run (dbt artefacts and log, git log, an aggregate profile of every table) and write `truth.json`.

Code faults that change nothing are thrown away: the generator also runs the clean workspace with the same seed and keeps a code fault only if the build fails or some table's profile differs. The ground truth records how many sites were tried.

## Fault types

| Type | Class | What changes | Ground-truth location |
|---|---|---|---|
| `schema_change` | data | a seed column is renamed, dropped, or (numeric only) turned into text | node, column |
| `late_or_missing_data` | data | the newest rows by a date column are removed (late), or all rows (missing) | node, date column or none |
| `duplicate_keys` | data | 5-20% of rows duplicated on the table's primary key | node, key column |
| `null_spike` | data | 30-70% of a column set to NULL | node, column |
| `distribution_shift` | data | a numeric column scaled (x100, x0.01 or x1.5-3), or a categorical column pushed towards one value | node, column |
| `model_logic_bug` | code | one SQL change in a model: aggregate swap, comparison, constant, `coalesce` default, operator | model, output column when the change sits in one, commit |
| `broken_join` | code | left join to inner join, inner to left, or a join condition made always true | model, commit |
| `timezone_error` | data | a timestamp column shifted by 1-9 hours; for a date column, a share of rows moved by a day | node, column |

`node` is the node that models read: the source for stripe, the seed for jaffle_shop and court_cases. `physical` is where the change was written.

## Ground truth (`truth.json`, schema version 1)

```json
{
  "schema_version": 1,
  "incident_id": "inc_jaffle_shop_dev_004",
  "project": "jaffle_shop",
  "split": "dev",
  "seed": 200004,
  "fault": {"type": "null_spike", "class": "data", "params": {"fraction": 0.41, "rows_nulled": 41}},
  "location": {"node": "seed.jaffle_shop.raw_customers", "column": "first_name", "commit": null,
               "physical": "seed.jaffle_shop.raw_customers", "file": "seeds/raw_customers.csv"},
  "observed": {"dbt_status": "success", "failed_tests": [], "warned_tests": [], "error_nodes": [],
               "skipped_nodes": 0, "steps": {"build": 0}},
  "generation": {"attempts": 1},
  "hashes": {"inputs": "sha256:..."}
}
```

`observed` comes from the run, never from a prediction. Code faults also record `changed_relations`: tables whose profile differs from the clean run. Clean runs have `"fault": null` and `"location": null`.

## Splits

Defined in `benchmark/plan.toml`.

- **train** and **dev** use jaffle_shop, stripe and court_cases (synthetic, our own; see `projects/court_cases/SOURCE.md`). Each split has its own seeds, and within a project every seed and every model belongs to exactly one split, so no node is faulted in both.
- **heldout** uses a third project that appears in no other split. It is generated once by the owner and frozen.

## What is committed and what is published

- Committed: `benchmark/<split>/<incident>/truth.json` and `benchmark/manifest.json` (every incident with the hashes of its ground truth and of its injected inputs, plus the sha256 of each split's archive).
- Published as GitHub Release assets: `benchmark-<split>.tar.gz`, the run directories. Their sha256 is in the manifest.
- Reproducible: the injected inputs and `truth.json` (same plan and code give the same hashes). Not byte-reproducible: dbt's own artefacts carry timestamps, so a regenerated archive has a different hash.

## Freezing heldout (owner, once)

The `heldout-guard` CI job fails any PR that touches `benchmark/heldout/`. The one exception is a PR with the `heldout-freeze` label, while `benchmark/heldout/` is still empty on `main`: it may add files there and change `benchmark/plan.toml` and `benchmark/manifest.json`, nothing else. After it merges, heldout is frozen for good.

1. The held-out project is vendored: `projects/jira` (fivetran/dbt_jira), already in `PROJECTS` in the Makefile.
2. On your own machine, from a clean `main`:
   ```
   git switch -c heldout-freeze
   make setup
   ```
3. Add the split to `benchmark/plan.toml`:
   ```toml
   [splits.heldout]
   projects = ["jira"]
   seed_base = 300000
   incidents_per_fault = 6
   clean_runs_per_project = 10
   location_share = 1
   ```
4. Generate it (about 40 minutes for a stripe-sized project):
   ```
   uv run faultline benchmark generate --split heldout
   ```
5. Commit `benchmark/heldout/`, `benchmark/manifest.json` and `benchmark/plan.toml`, push, open the PR, and add the `heldout-freeze` label. Check that `heldout-guard` passes, then merge.
6. Upload `dist/benchmark-heldout.tar.gz` to a GitHub Release.

Do not open the files in `benchmark/heldout/` or paste them into a chat. Only `faultline eval --split heldout` reads them, once, at the end.
