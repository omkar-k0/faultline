"""Propose: candidate root causes for one incident, from lineage and history.

In a dbt project a table's output can change for two reasons only: its inputs
changed, or its code changed. Data enters at seeds and sources, so data causes
are proposed there; models are proposed only as code causes, with the commit
that changed them. Every candidate is upstream of (or at) a symptom.

Proposing is deliberately broad. Whether a candidate holds is decided by its
test in `checks.py`, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from faultline.eval.loader import Commit
from faultline.incidents.manager import Group
from faultline.monitors.core import is_key
from faultline.triage.evidence import RunContext

Kind = Literal["source_table", "source_column", "duplicate_rows", "code_change"]
KIND_ORDER: dict[str, int] = {
    "duplicate_rows": 0,
    "source_column": 1,
    "source_table": 2,
    "code_change": 3,
}


@dataclass(frozen=True, order=True)
class Hypothesis:
    kind: Kind
    node: str
    column: str | None = None
    commit: str | None = None

    def sort_key(self) -> tuple[int, str, str, str]:
        return (KIND_ORDER[self.kind], self.node, self.column or "", self.commit or "")

    def describe(self) -> str:
        where = f"{self.node}.{self.column}" if self.column else self.node
        if self.kind == "code_change":
            return f"code change in {where} (commit {(self.commit or '')[:7]})"
        return {
            "source_table": f"rows of {where} changed (missing, late or extra)",
            "source_column": f"values of {where} changed",
            "duplicate_rows": f"duplicate rows in {self.node} (key {self.column})",
        }[self.kind]


def file_matches(original_file_path: str | None, path: str) -> bool:
    """A commit's file is a node's file: same path, or the same path inside a package folder."""
    if not original_file_path:
        return False
    return path == original_file_path or path.endswith("/" + original_file_path)


def changes_to(ctx: RunContext, node: str) -> list[Commit]:
    """Commits that changed a model's file, leaving out the commit that created it."""
    n = ctx.project.nodes.get(node)
    if n is None or n.resource_type != "model":
        return []
    touching = [
        c for c in ctx.history if any(file_matches(n.original_file_path, f) for f in c.files)
    ]
    return touching[1:]  # history is oldest first; the first touch created the file


def _profile_columns(ctx: RunContext, node: str) -> list[str]:
    entry = ctx.profile.get(node) or {}
    cols = entry.get("columns") or {}
    if not cols and ctx.references:
        cols = (ctx.references[0].get(node) or {}).get("columns") or {}
    return sorted(cols)


def propose(ctx: RunContext, group: Group) -> list[Hypothesis]:
    found: set[Hypothesis] = set()
    symptom_columns: dict[str, set[str]] = {}
    for s in group.symptoms:
        if s.column:
            symptom_columns.setdefault(s.node, set()).add(s.column)
    for s in group.symptoms:
        upstream = ctx.table_ancestors(s.node) | {s.node}
        for node in sorted(upstream):
            if ctx.is_root(node):
                found.add(Hypothesis("source_table", node))
                for col in _profile_columns(ctx, node):
                    if is_key(col):
                        found.add(Hypothesis("duplicate_rows", node, col))
            for commit in changes_to(ctx, node):
                found.add(Hypothesis("code_change", node, None, commit.hash))
                for col in sorted(symptom_columns.get(node, ())):
                    found.add(Hypothesis("code_change", node, col, commit.hash))
        if s.column:
            if ctx.is_root(s.node):
                found.add(Hypothesis("source_column", s.node, s.column))
            for ref in ctx.column_ancestors(s.node, s.column):
                if ctx.is_root(ref.node):
                    found.add(Hypothesis("source_column", ref.node, ref.column))
    return sorted(found, key=Hypothesis.sort_key)
