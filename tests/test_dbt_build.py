"""The vendored projects build on DuckDB. `make setup` builds them first."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECTS = Path(__file__).resolve().parents[1] / "projects"


@pytest.mark.dbt
@pytest.mark.parametrize("name", ["jaffle_shop"])
def test_last_build_succeeded(name: str) -> None:
    results_file = PROJECTS / name / "target" / "run_results.json"
    if not results_file.exists():
        pytest.fail(f"{results_file} missing: run `make build-projects` first")
    results = json.loads(results_file.read_text())["results"]
    assert results, "dbt build ran no nodes"
    failed = [r["unique_id"] for r in results if r["status"] not in {"success", "pass"}]
    assert failed == []
