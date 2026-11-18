"""The vendored projects build on DuckDB and actually carry data.

`make setup` builds them first. A green dbt build is not enough: the first
stripe build passed every test while every staging table was empty, because
the sources were read before the seeds were loaded.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

PROJECTS = Path(__file__).resolve().parents[1] / "projects"

# Relations that are empty in a correct build, because the shipped seed data
# has no rows that reach them. Anything else empty is a broken build.
EXPECTED_EMPTY = {
    "jaffle_shop": set(),
    "stripe": {"stripe__ending_balance_reconciliation_itemized_4", "stripe__payout_itemized_3"},
}


@pytest.mark.dbt
@pytest.mark.parametrize("name", sorted(EXPECTED_EMPTY))
def test_last_build_succeeded(name: str) -> None:
    results_file = PROJECTS / name / "target" / "run_results.json"
    if not results_file.exists():
        pytest.fail(f"{results_file} missing: run `make build-projects` first")
    results = json.loads(results_file.read_text())["results"]
    assert results, "dbt build ran no nodes"
    failed = [r["unique_id"] for r in results if r["status"] not in {"success", "pass"}]
    assert failed == []


@pytest.mark.dbt
@pytest.mark.parametrize("name", sorted(EXPECTED_EMPTY))
def test_models_hold_rows(name: str) -> None:
    manifest = json.loads((PROJECTS / name / "target" / "manifest.json").read_text())
    db = next((PROJECTS / name / "target").glob("*.duckdb"))
    con = duckdb.connect(str(db), read_only=True)
    try:
        empty = set()
        for node in manifest["nodes"].values():
            if node["resource_type"] != "model" or node["config"]["materialized"] == "ephemeral":
                continue
            rows = con.sql(f"select count(*) from {node['relation_name']}").fetchall()[0][0]
            if rows == 0:
                empty.add(node["name"])
    finally:
        con.close()
    assert empty == EXPECTED_EMPTY[name]
