"""Column-level lineage from compiled SQL, using sqlglot.

For every column of every model the result is one `ColumnLineage` entry:
- `resolved`: the upstream columns one dbt hop away, each with a transform kind;
- `constant`: the column comes from literals only, so it has no upstream;
- `unresolved`: lineage could not be computed, with the reason.
No column is dropped silently.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import networkx as nx
import sqlglot
from sqlglot import exp
from sqlglot.lineage import Node as SqlNode
from sqlglot.lineage import lineage as sqlglot_lineage
from sqlglot.optimizer.qualify import qualify

from faultline.collectors.dbt_artifacts import Node, Project

TransformKind = Literal["direct", "renamed", "derived", "aggregated"]
Status = Literal["resolved", "constant", "unresolved"]

EPHEMERAL_CTE_PREFIX = "__dbt__cte__"
_KIND_RANK: dict[TransformKind, int] = {"direct": 0, "renamed": 1, "derived": 2, "aggregated": 3}
LINEAGE_TYPES = frozenset({"model", "snapshot"})


@dataclass(frozen=True, order=True)
class ColumnRef:
    node: str
    column: str

    def __str__(self) -> str:
        return f"{self.node}.{self.column}"


@dataclass(frozen=True)
class UpstreamEdge:
    source: ColumnRef
    kind: TransformKind


@dataclass(frozen=True)
class ColumnLineage:
    target: ColumnRef
    status: Status
    upstream: tuple[UpstreamEdge, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class ProjectLineage:
    project: Project
    columns: Mapping[ColumnRef, ColumnLineage]
    # Columns of each node, including columns derived from SQL for ephemeral models.
    node_columns: Mapping[str, tuple[str, ...]]

    def undeclared_edges(self) -> list[tuple[ColumnRef, UpstreamEdge]]:
        """Edges whose source node is read by the SQL but missing from dbt's depends_on."""
        found: list[tuple[ColumnRef, UpstreamEdge]] = []
        for entry in self.columns.values():
            declared = self.project.nodes[entry.target.node].depends_on
            found.extend((entry.target, e) for e in entry.upstream if e.source.node not in declared)
        return found

    def coverage(self) -> dict[str, int]:
        counts = {"total": 0, "resolved": 0, "constant": 0, "unresolved": 0}
        for entry in self.columns.values():
            counts["total"] += 1
            counts[entry.status] += 1
        return counts


def _key(*parts: str | None) -> tuple[str, ...]:
    return tuple((p or "").lower() for p in parts)


class _RelationIndex:
    """Map a table reference in compiled SQL back to a dbt node id."""

    def __init__(self, nodes: list[Node]) -> None:
        self.full: dict[tuple[str, ...], str] = {}
        self.partial: dict[tuple[str, ...], set[str]] = {}
        for node in nodes:
            if node.resource_type == "test" or node.is_ephemeral:
                continue
            self.full[_key(node.database, node.schema, node.identifier)] = node.unique_id
            self.partial.setdefault(_key(node.schema, node.identifier), set()).add(node.unique_id)
            self.partial.setdefault(_key(node.identifier), set()).add(node.unique_id)

    def lookup(self, table: exp.Table) -> str | None:
        hit = self.full.get(_key(table.catalog, table.db, table.name))
        if hit:
            return hit
        key = _key(table.db, table.name) if table.db else _key(table.name)
        candidates = self.partial.get(key, set())
        return next(iter(candidates)) if len(candidates) == 1 else None


def _schema(project: Project) -> dict[str, dict[str, dict[str, dict[str, str]]]]:
    schema: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    for node in project.nodes.values():
        if not node.columns or node.is_ephemeral or node.resource_type == "test":
            continue
        tables = schema.setdefault(node.database or "", {}).setdefault(node.schema or "", {})
        tables[node.identifier or node.name] = {
            c.name: (c.data_type or "UNKNOWN") for c in node.columns
        }
    return schema


def _output_columns(sql: str, schema: Mapping[str, Any], dialect: str) -> tuple[str, ...]:
    """Output column names of a SELECT, used for ephemeral models (no catalog entry)."""
    tree = qualify(sqlglot.parse_one(sql, dialect=dialect), schema=dict(schema), dialect=dialect)
    if not isinstance(tree, exp.Query):
        raise ValueError("compiled SQL is not a query")
    return tuple(tree.named_selects)


def _strip(expression: exp.Expr) -> exp.Expr:
    return expression.this if isinstance(expression, exp.Alias) else expression


def _kind(steps: list[exp.Expr], target: str, source: str) -> TransformKind:
    stripped = [_strip(e) for e in steps]
    if any(e.find(exp.Window) is not None for e in stripped):
        return "derived"
    if any(e.find(exp.AggFunc) is not None for e in stripped):
        return "aggregated"
    if all(isinstance(e, exp.Column) for e in stripped):
        return "direct" if target.lower() == source.lower() else "renamed"
    return "derived"


def _column_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].strip('"')


def _boundaries(
    root: SqlNode,
) -> Iterator[tuple[list[SqlNode], exp.Table | str | None]]:
    """Yield (path, boundary) for each way the root column leaves this model.

    The boundary is a table (another relation), an ephemeral model name, or None
    when the path ends in something that is not a column (a literal).
    """
    stack: list[list[SqlNode]] = [[root]]
    while stack:
        path = stack.pop()
        node = path[-1]
        ref = node.reference_node_name or ""
        if len(path) > 1 and ref.startswith(EPHEMERAL_CTE_PREFIX):
            yield path, ref.removeprefix(EPHEMERAL_CTE_PREFIX)
            continue
        if isinstance(node.expression, exp.Table):
            yield path, node.expression
            continue
        if not node.downstream:
            yield path, None
            continue
        stack.extend([*path, child] for child in node.downstream)


class _Resolver:
    def __init__(self, project: Project, dialect: str) -> None:
        self.project = project
        self.dialect = dialect
        self.schema = _schema(project)
        self.relations = _RelationIndex(list(project.nodes.values()))
        self.ephemeral_by_name = {
            n.name.lower(): n.unique_id for n in project.models if n.is_ephemeral
        }
        self.node_columns: dict[str, tuple[str, ...]] = {
            uid: n.column_names() for uid, n in project.nodes.items()
        }

    def columns_for(self, node: Node) -> tuple[str, ...] | str:
        """Column names of a model, or an error string if they cannot be found."""
        if node.columns:
            return node.column_names()
        if not node.compiled_code:
            return "no compiled SQL and no catalog entry"
        try:
            cols = _output_columns(node.compiled_code, self.schema, self.dialect)
        except Exception as exc:  # sqlglot raises many error types
            return f"could not read output columns: {type(exc).__name__}: {exc}"
        self.node_columns[node.unique_id] = cols
        return cols

    def _canonical(self, node_id: str, column: str) -> str:
        for known in self.node_columns.get(node_id, ()):
            if known.lower() == column.lower():
                return known
        return column

    def resolve_model(self, node: Node, columns: tuple[str, ...]) -> list[ColumnLineage]:
        """Lineage for every column of one model, one sqlglot pass when possible."""
        sql = node.compiled_code
        if not sql:
            return [
                ColumnLineage(ColumnRef(node.unique_id, c), "unresolved", reason="no compiled SQL")
                for c in columns
            ]
        try:
            roots = sqlglot_lineage(None, sql, schema=self.schema, dialect=self.dialect)
        except Exception:  # fall back to one column at a time for partial results
            return [self.resolve(node, column) for column in columns]
        assert isinstance(roots, dict)
        by_lower = {name.lower(): root for name, root in roots.items()}
        out = []
        for column in columns:
            root = by_lower.get(column.lower())
            if root is None:
                out.append(self.resolve(node, column))
            else:
                out.append(self._from_root(node, column, root))
        return out

    def resolve(self, node: Node, column: str) -> ColumnLineage:
        target = ColumnRef(node.unique_id, column)
        sql = node.compiled_code
        if not sql:
            return ColumnLineage(target, "unresolved", reason="no compiled SQL")
        try:
            root = sqlglot_lineage(column, sql, schema=self.schema, dialect=self.dialect)
        except Exception as exc:  # sqlglot raises many error types
            return ColumnLineage(
                target, "unresolved", reason=f"sqlglot: {type(exc).__name__}: {exc}"
            )
        assert isinstance(root, SqlNode)
        return self._from_root(node, column, root)

    def _from_root(self, node: Node, column: str, root: SqlNode) -> ColumnLineage:
        target = ColumnRef(node.unique_id, column)
        best: dict[ColumnRef, TransformKind] = {}
        for path, boundary in _boundaries(root):
            if boundary is None:
                continue
            last = path[-1]
            if isinstance(boundary, exp.Table):
                source_id = self.relations.lookup(boundary)
                if source_id is None:
                    return ColumnLineage(
                        target, "unresolved", reason=f"table {boundary.sql()} not in manifest"
                    )
            else:
                found = self.ephemeral_by_name.get(boundary.lower())
                if found is None:
                    return ColumnLineage(
                        target, "unresolved", reason=f"ephemeral CTE {boundary} not in manifest"
                    )
                source_id = found
            steps = [p.expression for p in path[:-1]]
            if source_id == node.unique_id:
                continue  # incremental self-reference ({{ this }})
            source_col = self._canonical(source_id, _column_of(last.name))
            kind = _kind(steps, column, source_col)
            ref = ColumnRef(source_id, source_col)
            if ref not in best or _KIND_RANK[kind] > _KIND_RANK[best[ref]]:
                best[ref] = kind

        if not best:
            return ColumnLineage(target, "constant")
        edges = tuple(UpstreamEdge(ref, best[ref]) for ref in sorted(best))
        return ColumnLineage(target, "resolved", upstream=edges)


def build_column_lineage(project: Project, dialect: str | None = None) -> ProjectLineage:
    resolver = _Resolver(project, dialect or project.adapter_type or "duckdb")
    entries: dict[ColumnRef, ColumnLineage] = {}

    # Ephemeral models first, so their derived columns are known downstream.
    lineage_nodes = sorted(
        (n for n in project.nodes.values() if n.resource_type in LINEAGE_TYPES),
        key=lambda n: (not n.is_ephemeral, n.unique_id),
    )
    for node in lineage_nodes:
        cols = resolver.columns_for(node)
        if isinstance(cols, str):
            ref = ColumnRef(node.unique_id, "*")
            entries[ref] = ColumnLineage(ref, "unresolved", reason=cols)
            continue
        for entry in resolver.resolve_model(node, cols):
            entries[entry.target] = entry

    return ProjectLineage(project=project, columns=entries, node_columns=resolver.node_columns)


def build_column_graph(lineage: ProjectLineage) -> Any:
    """`networkx.DiGraph` over ColumnRef nodes, edge source -> target with `kind`."""
    graph = nx.DiGraph()
    for node_id, cols in lineage.node_columns.items():
        node = lineage.project.nodes.get(node_id)
        if node is None or node.resource_type == "test":
            continue
        for col in cols:
            graph.add_node(ColumnRef(node_id, col), resource_type=node.resource_type)
    for entry in lineage.columns.values():
        graph.add_node(entry.target, status=entry.status)
        for edge in entry.upstream:
            graph.add_edge(edge.source, entry.target, kind=edge.kind)
    return graph
