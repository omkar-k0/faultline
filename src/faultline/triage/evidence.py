"""Gather: everything triage may use about one run, and the symptoms in it.

A symptom is one thing that looks wrong: a monitor anomaly (M4) or a failed dbt
test or model. Nodes that dbt skipped because something upstream failed are
recorded separately; they are consequences, not symptoms of their own.

The context holds the run's own artefacts (manifest and catalog, so lineage is
the lineage of that run's code), its profile, the known-good reference
profiles, and the cleaned git history. No raw rows, and no ground truth.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from faultline.collectors.dbt_artifacts import Project, load_project
from faultline.eval.loader import Commit
from faultline.lineage.column import ColumnRef, ProjectLineage, build_column_graph
from faultline.lineage.column import build_column_lineage as _build_column_lineage
from faultline.lineage.table import build_table_graph
from faultline.monitors.core import NUMERIC_STATS, Anomaly, Profile

ROOT_TYPES = frozenset({"seed", "source"})

# How strong one symptom is as evidence. Structural changes cannot come from
# natural variation; statistics can, a little.
STRENGTH = {
    "schema": 3,
    "dbt_error": 3,
    "duplicates": 3,
    "dbt_test": 2,
    "freshness": 2,
    "time_shift": 2,
    "volume": 2,
    "null_rate": 1,
    "distribution": 1,
}


@dataclass(frozen=True)
class Symptom:
    source: str  # monitor name, "dbt_test" or "dbt_error"
    node: str
    column: str | None
    observed: str
    expected: str
    severity: float  # inf for structural

    @property
    def strength(self) -> int:
        # A new column on its own breaks no consumer; a missing one does.
        if self.source == "schema" and self.observed == "new":
            return 2
        return STRENGTH.get(self.source, 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "node": self.node,
            "column": self.column,
            "observed": self.observed,
            "expected": self.expected,
            "severity": "inf" if self.severity == float("inf") else round(self.severity, 6),
        }


def from_anomaly(a: Anomaly) -> Symptom:
    return Symptom(a.monitor, a.node, a.column, str(a.observed), a.expected, a.severity)


def dbt_symptoms(
    run_results: Mapping[str, Any] | None, project: Project
) -> tuple[list[Symptom], frozenset[str]]:
    """Failed tests and errored nodes as symptoms; skipped nodes separately."""
    symptoms: list[Symptom] = []
    skipped: set[str] = set()
    for result in (run_results or {}).get("results", []):
        uid, status = str(result.get("unique_id", "")), str(result.get("status", ""))
        node = project.nodes.get(uid)
        if status == "skipped":
            skipped.add(uid)
        elif node is not None and node.resource_type == "test" and status in {"fail", "error"}:
            symptoms.append(
                Symptom(
                    "dbt_test",
                    node.attached_node or uid,
                    node.test_column,
                    f"{node.test_name or 'test'} {status}",
                    "pass",
                    float("inf"),
                )
            )
        elif node is not None and status == "error":
            symptoms.append(Symptom("dbt_error", uid, None, "error", "success", float("inf")))
    return symptoms, frozenset(skipped)


def _lineage_key(project: Project) -> str:
    parts = [
        (n.unique_id, n.compiled_code or "", n.column_names(), n.depends_on)
        for n in sorted(project.nodes.values(), key=lambda n: n.unique_id)
    ]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


_LINEAGE_CACHE: dict[str, tuple[ProjectLineage, Any]] = {}


def column_lineage(project: Project) -> tuple[ProjectLineage, Any]:
    """Column lineage and its graph, cached by the run's code and columns.

    Runs with the same compiled SQL and catalog columns share one lineage, so
    a split's clean and data-fault runs are parsed once per project.
    """
    key = _lineage_key(project)
    if key not in _LINEAGE_CACHE:
        lineage = _build_column_lineage(project)
        _LINEAGE_CACHE[key] = (lineage, build_column_graph(lineage))
    cached_lineage, graph = _LINEAGE_CACHE[key]
    return cached_lineage, graph


def is_measured(stats: Mapping[str, Any]) -> bool:
    """A column whose profile carries numeric or time statistics."""
    return any(stats.get(s) is not None for s in (*NUMERIC_STATS, "max", "min"))


@dataclass
class RunContext:
    run_id: str
    project: Project
    tables: Any  # networkx.DiGraph, parent -> child
    columns: Any  # networkx.DiGraph over ColumnRef, source -> target
    profile: Profile
    references: Sequence[Profile]
    history: tuple[Commit, ...]
    skipped: frozenset[str]
    _index: dict[tuple[str, str], ColumnRef] | None = field(default=None, repr=False)

    def resource_type(self, node: str) -> str:
        n = self.project.nodes.get(node)
        return n.resource_type if n else "external"

    def is_root(self, node: str) -> bool:
        return self.resource_type(node) in ROOT_TYPES

    def table_ancestors(self, node: str) -> set[str]:
        return set(nx.ancestors(self.tables, node)) if node in self.tables else set()

    def table_descendants(self, node: str) -> set[str]:
        return set(nx.descendants(self.tables, node)) if node in self.tables else set()

    def parents(self, node: str) -> list[str]:
        return sorted(self.tables.predecessors(node)) if node in self.tables else []

    def column_ref(self, node: str, column: str) -> ColumnRef | None:
        """The lineage graph's node for a column, matched case-insensitively."""
        if ColumnRef(node, column) in self.columns:
            return ColumnRef(node, column)
        if self._index is None:
            self._index = {(r.node, r.column.lower()): r for r in self.columns.nodes}
        return self._index.get((node, column.lower()))

    def column_ancestors(self, node: str, column: str) -> set[ColumnRef]:
        ref = self.column_ref(node, column)
        return set(nx.ancestors(self.columns, ref)) if ref is not None else set()

    def column_stats(self, node: str, column: str) -> dict[str, Any] | None:
        cols = (self.profile.get(node) or {}).get("columns") or {}
        for name, stats in cols.items():
            if name.lower() == column.lower():
                return dict(stats)
        return None


def build_context(
    run_id: str,
    run_dir: Path,
    profile: Profile,
    references: Sequence[Profile],
    history: tuple[Commit, ...],
    run_results: Mapping[str, Any] | None,
) -> tuple[RunContext, list[Symptom]]:
    """Load the run's artefacts and lineage; return the context and dbt symptoms."""
    project = load_project(run_dir.parent, target=run_dir.name)
    _lineage, graph = column_lineage(project)
    symptoms, skipped = dbt_symptoms(run_results, project)
    ctx = RunContext(
        run_id=run_id,
        project=project,
        tables=build_table_graph(project),
        columns=graph,
        profile=profile,
        references=references,
        history=history,
        skipped=skipped,
    )
    return ctx, symptoms
