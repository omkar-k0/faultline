from __future__ import annotations

from pathlib import Path

import pytest

from faultline.collectors.dbt_artifacts import Column, Node, Project, load_project
from faultline.lineage.column import ProjectLineage, build_column_lineage

ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ROOT / "projects"


def _built(name: str) -> Path:
    path = PROJECTS / name
    if not (path / "target" / "catalog.json").is_file():
        pytest.fail(f"{name} is not built: run `make build-projects` first")
    return path


@pytest.fixture(scope="session")
def jaffle() -> Project:
    return load_project(_built("jaffle_shop"))


@pytest.fixture(scope="session")
def jaffle_lineage(jaffle: Project) -> ProjectLineage:
    return build_column_lineage(jaffle)


@pytest.fixture(scope="session")
def stripe() -> Project:
    return load_project(_built("stripe"))


@pytest.fixture(scope="session")
def stripe_lineage(stripe: Project) -> ProjectLineage:
    return build_column_lineage(stripe)


def table(name: str, columns: list[str], resource_type: str = "seed") -> Node:
    """A seed or source with known columns, in database db, schema main."""
    return Node(
        unique_id=f"{resource_type}.p.{name}",
        resource_type=resource_type,
        name=name,
        package="p",
        database="db",
        schema="main",
        identifier=name,
        materialized="seed" if resource_type == "seed" else None,
        depends_on=(),
        compiled_code=None,
        original_file_path=None,
        columns=tuple(Column(c, "INTEGER") for c in columns),
    )


def model(
    name: str,
    sql: str,
    depends_on: list[str],
    columns: list[str] | None = None,
    materialized: str = "table",
) -> Node:
    return Node(
        unique_id=f"model.p.{name}",
        resource_type="model",
        name=name,
        package="p",
        database="db",
        schema="main",
        identifier=name,
        materialized=materialized,
        depends_on=tuple(depends_on),
        compiled_code=sql,
        original_file_path=f"models/{name}.sql",
        columns=tuple(Column(c, "INTEGER") for c in (columns or [])),
    )


def project(*nodes: Node) -> Project:
    return Project(
        name="p",
        root=Path("p"),
        adapter_type="duckdb",
        dbt_version="1.12",
        nodes={n.unique_id: n for n in nodes},
    )
