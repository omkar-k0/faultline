# Source

- Origin: https://github.com/dbt-labs/jaffle_shop_duckdb
- Commit: 20cc904370818ceab08cf19f8fd196e9e81def88 (2026-09-28)
- Licence: Apache License 2.0, copied unchanged in `LICENCE`
- Copied: `dbt_project.yml`, `models/`, `seeds/`
- Changed: `profiles.yml` is our own. It writes the DuckDB file under `target/` and uses 4 threads.
- Not copied: Dockerfile, images, `etc/`, the upstream Python packaging.
