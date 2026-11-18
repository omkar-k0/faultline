"""Where faults can go in a test project.

Built from the clean, already-built project (its manifest, catalog and seed
files). Each seed column gets a role inferred from its name and values, and a
flag for whether any model reads it (a fault nobody reads is not an incident).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import networkx as nx

from faultline.collectors.dbt_artifacts import Project, load_project
from faultline.inject.workspace import read_csv
from faultline.lineage.column import ColumnRef, build_column_graph, build_column_lineage

Role = Literal["key", "boolean", "timestamp", "date", "numeric", "categorical", "text", "empty"]

TIMESTAMP_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S")
DATE_FORMAT = "%Y-%m-%d"
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_REF = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")


def parse_timestamp(value: str) -> datetime | None:
    for fmt in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, DATE_FORMAT)
    except ValueError:
        return None


def infer_role(name: str, values: Sequence[str]) -> Role:
    present = [v for v in values if v != ""]
    if not present:
        return "empty"
    lowered = name.lower()
    if lowered == "id" or lowered.endswith("_id"):
        return "key"
    if {v.lower() for v in present} <= {"true", "false"}:
        return "boolean"
    if all(parse_timestamp(v) for v in present):
        return "timestamp"
    if all(parse_date(v) for v in present):
        return "date"
    if all(_NUMBER.match(v) for v in present):
        return "numeric"
    distinct = len(set(present))
    if 2 <= distinct <= max(5, len(present) // 3):
        return "categorical"
    return "text"


@dataclass(frozen=True)
class SeedColumn:
    seed: str  # seed node id
    column: str
    role: Role
    read_downstream: bool
    fill_rate: float
    unique: bool


@dataclass(frozen=True)
class Seed:
    node: str  # seed node id, the physical place the fault is written
    relation: str  # node id that models read: the source for stripe, the seed for jaffle_shop
    file: str  # path inside the workspace
    rows: int
    columns: tuple[SeedColumn, ...]
    is_parent: bool  # another table's relationships test points at it: never drop its rows

    def column(self, name: str) -> SeedColumn:
        return next(c for c in self.columns if c.column == name)


@dataclass(frozen=True)
class ModelSite:
    node: str
    file: str  # path inside the workspace


@dataclass(frozen=True)
class FaultCatalog:
    project: str
    project_dir: Path
    seeds: tuple[Seed, ...]
    models: tuple[ModelSite, ...]
    root_package: str
    model_columns: dict[str, tuple[str, ...]]

    def seed(self, node: str) -> Seed:
        return next(s for s in self.seeds if s.node == node)


def _package_dir(package: str, root_package: str) -> Path:
    return Path(".") if package == root_package else Path("packages") / package


def _root_package(project_dir: Path) -> str:
    for line in (project_dir / "dbt_project.yml").read_text().splitlines():
        match = re.match(r"^name:\s*['\"]?([\w-]+)['\"]?", line)
        if match:
            return match.group(1)
    raise ValueError(f"{project_dir}/dbt_project.yml has no name")


def _parent_seeds(project: Project, graph: Any, relation_of: dict[str, str]) -> set[str]:
    """Seeds whose rows a relationships test relies on (the `to` side and its `field`)."""
    seeds_by_relation = {rel: seed for seed, rel in relation_of.items()}
    names = {n.name: n.unique_id for n in project.nodes.values() if n.resource_type != "test"}
    parents: set[str] = set()
    for test in project.tests:
        if test.test_name != "relationships":
            continue
        kwargs = dict(test.test_kwargs)
        match = _REF.search(kwargs.get("to", ""))
        target = names.get(match.group(1)) if match else None
        field_name = kwargs.get("field")
        if target is None or field_name is None:
            continue
        start = next(
            (r for r in graph.nodes if r.node == target and r.column.lower() == field_name.lower()),
            None,
        )
        if start is None:
            continue
        for ref in nx.ancestors(graph, start) | {start}:
            if ref.node in seeds_by_relation:
                parents.add(seeds_by_relation[ref.node])
    return parents


def build_catalog(project_dir: Path) -> FaultCatalog:
    """Read the clean built project. `make build-projects` must have run."""
    project = load_project(project_dir)
    lineage = build_column_lineage(project)
    graph = build_column_graph(lineage)
    root_package = _root_package(project_dir)

    # A source and a seed are the same relation when database, schema and identifier match.
    by_relation = {
        (n.database or "", n.schema or "", (n.identifier or "").lower()): n.unique_id
        for n in project.by_type("source")
    }
    relation_of: dict[str, str] = {}
    for seed in project.by_type("seed"):
        key = (seed.database or "", seed.schema or "", (seed.identifier or "").lower())
        relation_of[seed.unique_id] = by_relation.get(key, seed.unique_id)

    parents = _parent_seeds(project, graph, relation_of)

    seeds: list[Seed] = []
    for node in sorted(project.by_type("seed"), key=lambda n: n.unique_id):
        if not node.original_file_path:
            continue
        rel_file = _package_dir(node.package, root_package) / node.original_file_path
        header, rows = read_csv(project_dir / rel_file)
        relation = relation_of[node.unique_id]
        cols: list[SeedColumn] = []
        for i, name in enumerate(header):
            values = [r[i] if i < len(r) else "" for r in rows]
            present = [v for v in values if v != ""]
            ref = ColumnRef(relation, name)
            read = ref in graph and graph.out_degree(ref) > 0
            cols.append(
                SeedColumn(
                    seed=node.unique_id,
                    column=name,
                    role=infer_role(name, values),
                    read_downstream=bool(read),
                    fill_rate=len(present) / len(values) if values else 0.0,
                    unique=len(set(present)) == len(present) == len(values),
                )
            )
        seeds.append(
            Seed(
                node=node.unique_id,
                relation=relation,
                file=str(rel_file),
                rows=len(rows),
                columns=tuple(cols),
                is_parent=node.unique_id in parents,
            )
        )

    models: list[ModelSite] = []
    for node in sorted(project.models, key=lambda n: n.unique_id):
        if not node.original_file_path:
            continue
        rel_file = _package_dir(node.package, root_package) / node.original_file_path
        if (project_dir / rel_file).is_file():
            models.append(ModelSite(node=node.unique_id, file=str(rel_file)))

    return FaultCatalog(
        project=project_dir.name,
        project_dir=project_dir,
        seeds=tuple(seeds),
        models=tuple(models),
        root_package=root_package,
        model_columns={m.node: lineage.node_columns.get(m.node, ()) for m in models},
    )
