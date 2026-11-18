"""Impact analysis over the table and column graphs.

Downstream answers "what breaks if this breaks". Upstream answers "where can a
bad value here come from". Every hit carries the shortest path from the start,
so a report can cite the lineage it relied on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import networkx as nx

from faultline.collectors.dbt_artifacts import Project
from faultline.lineage.column import ColumnRef, ProjectLineage, build_column_graph
from faultline.lineage.table import build_table_graph

Direction = Literal["downstream", "upstream"]


class TargetError(ValueError):
    """A node or column name did not match exactly one thing in the project."""


@dataclass(frozen=True)
class Hit:
    target: str
    resource_type: str
    distance: int
    path: tuple[str, ...]


@dataclass(frozen=True)
class ImpactResult:
    start: str
    level: Literal["node", "column"]
    direction: Direction
    hits: tuple[Hit, ...]
    # Tests attached to the start or to any hit (columns: tests on that column).
    tests: tuple[str, ...]


def resolve_node(project: Project, name: str) -> str:
    """Match a unique id, or a bare name, to one non-test node."""
    if name in project.nodes:
        return name
    matches = sorted(
        uid
        for uid, node in project.nodes.items()
        if node.resource_type != "test" and name.lower() in {node.name.lower(), uid.lower()}
    )
    if not matches:
        raise TargetError(f"no node named {name!r}")
    if len(matches) > 1:
        raise TargetError(f"{name!r} is ambiguous: {', '.join(matches)}")
    return matches[0]


def resolve_target(project: Project, lineage: ProjectLineage, text: str) -> str | ColumnRef:
    """Parse `node` or `node.column`. A full node id is tried before splitting."""
    try:
        return resolve_node(project, text)
    except TargetError as node_error:
        if "." not in text:
            raise
        node_part, column = text.rsplit(".", 1)
        try:
            node_id = resolve_node(project, node_part)
        except TargetError:
            raise node_error from None
        for known in lineage.node_columns.get(node_id, ()):
            if known.lower() == column.lower():
                return ColumnRef(node_id, known)
        raise TargetError(f"{node_id} has no column {column!r}") from None


def _walk(graph: Any, start: Any, direction: Direction) -> list[tuple[Any, list[Any]]]:
    view = graph if direction == "downstream" else graph.reverse(copy=False)
    paths: dict[Any, list[Any]] = nx.single_source_shortest_path(view, start)
    found = [(n, p) for n, p in paths.items() if n != start]
    return sorted(found, key=lambda item: (len(item[1]), str(item[0])))


def node_impact(project: Project, node_id: str, direction: Direction) -> ImpactResult:
    graph = build_table_graph(project)
    if node_id not in graph:
        raise TargetError(f"no node {node_id!r}")
    hits = []
    tests = []
    for target, path in _walk(graph, node_id, direction):
        rtype = graph.nodes[target].get("resource_type", "external")
        if rtype == "test":
            tests.append(target)
            continue
        hits.append(Hit(target, rtype, len(path) - 1, tuple(path)))
    if direction == "upstream":
        tests = [t.unique_id for t in project.tests if node_id in t.depends_on]
    return ImpactResult(node_id, "node", direction, tuple(hits), tuple(sorted(set(tests))))


def column_impact(
    project: Project, lineage: ProjectLineage, start: ColumnRef, direction: Direction
) -> ImpactResult:
    graph = build_column_graph(lineage)
    if start not in graph:
        raise TargetError(f"no column {start}")
    hits = []
    touched = {start}
    for target, path in _walk(graph, start, direction):
        touched.add(target)
        rtype = project.nodes[target.node].resource_type if target.node in project.nodes else ""
        hits.append(Hit(str(target), rtype, len(path) - 1, tuple(str(p) for p in path)))
    keys = {(ref.node, ref.column.lower()) for ref in touched}
    tests = sorted(
        t.unique_id
        for t in project.tests
        if t.attached_node
        and t.test_column
        and (t.attached_node, t.test_column.strip('"').lower()) in keys
    )
    return ImpactResult(str(start), "column", direction, tuple(hits), tuple(tests))


def impact(
    project: Project, lineage: ProjectLineage, target: str, direction: Direction = "downstream"
) -> ImpactResult:
    resolved = resolve_target(project, lineage, target)
    if isinstance(resolved, ColumnRef):
        return column_impact(project, lineage, resolved, direction)
    return node_impact(project, resolved, direction)
