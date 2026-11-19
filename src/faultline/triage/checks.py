"""Test: try to knock down each hypothesis with the evidence of the run.

In benchmark mode the evidence is the recorded aggregate profile of every
table (each value was produced by an aggregate SQL query when the run was
captured), the known-good reference profiles, lineage, compiled SQL and the
cleaned git history. Against a live warehouse the same checks would run as
SQL; the benchmark archives hold no databases.

A hypothesis passes in one of two modes:
- observed: the cause's own location shows a symptom (a source column whose
  null share jumped, a model a commit changed whose inputs are all normal);
- inferred: by elimination. A model column is off, no commit changed any
  model on its path, and every measured input is normal, so the change came
  through an input the profile cannot measure (text columns have no
  distribution statistics). Inferred causes are reported as such.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from faultline.incidents.manager import Group
from faultline.monitors.core import MonitorConfig, is_key
from faultline.triage.evidence import RunContext, is_measured
from faultline.triage.hypotheses import Hypothesis, changes_to, file_matches

Mode = Literal["observed", "inferred", "failed"]
NEAR_UNIQUE = 0.95  # profile distinct counts are approximate


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Result:
    hypothesis: Hypothesis
    mode: Mode
    strength: int
    severity: float
    explains: tuple[int, ...]  # indices into the group's symptoms
    checks: tuple[Check, ...] = field(default=())

    @property
    def passed(self) -> bool:
        return self.mode != "failed"

    def as_dict(self, group: Group) -> dict[str, Any]:
        h = self.hypothesis
        return {
            "kind": h.kind,
            "node": h.node,
            "column": h.column,
            "commit": h.commit,
            "description": h.describe(),
            "mode": self.mode,
            "strength": self.strength,
            "explains": [group.symptoms[i].as_dict() for i in self.explains],
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
            "lineage": lineage_paths(group, self),
        }


def lineage_paths(group: Group, result: Result) -> list[str]:
    """Where each explained symptom sits relative to the cause, as text."""
    h = result.hypothesis
    out = []
    for i in result.explains:
        s = group.symptoms[i]
        here = f"{s.node}.{s.column}" if s.column else s.node
        origin = f"{h.node}.{h.column}" if h.column else h.node
        out.append(here if here == origin else f"{origin} -> {here}")
    return sorted(set(out))


def _same(a: str | None, b: str | None) -> bool:
    return (a or "").lower() == (b or "").lower()


def _at(group: Group, node: str, column: str | None = None, any_column: bool = False) -> list[int]:
    return [
        i
        for i, s in enumerate(group.symptoms)
        if s.node == node and (any_column or _same(s.column, column))
    ]


def explains(ctx: RunContext, group: Group, h: Hypothesis) -> tuple[int, ...]:
    out = []
    for i, s in enumerate(group.symptoms):
        downstream = s.node == h.node or h.node in ctx.table_ancestors(s.node)
        if h.kind == "source_column" and h.column and s.column:
            if s.node == h.node:
                hit = _same(s.column, h.column)
            else:
                ref = ctx.column_ref(h.node, h.column)
                hit = ref is not None and ref in ctx.column_ancestors(s.node, s.column)
        else:
            hit = downstream
        if hit:
            out.append(i)
    return tuple(out)


def _strength(group: Group, idx: Sequence[int]) -> tuple[int, float]:
    if not idx:
        return 0, 0.0
    return max(group.symptoms[i].strength for i in idx), max(
        group.symptoms[i].severity for i in idx
    )


def _rows(profile: dict[str, Any], node: str) -> int | None:
    entry = profile.get(node) or {}
    rows = entry.get("rows")
    return rows if isinstance(rows, int) and not entry.get("missing") else None


def _distinct(profile: dict[str, Any], node: str, column: str) -> int | None:
    cols = (profile.get(node) or {}).get("columns") or {}
    for name, stats in cols.items():
        if name.lower() == column.lower() and isinstance(stats.get("distinct"), int):
            return int(stats["distinct"])
    return None


def check_duplicates(ctx: RunContext, h: Hypothesis, cfg: MonitorConfig) -> list[Check]:
    """Rows went up while the key's distinct count did not: the new rows repeat keys."""
    assert h.column is not None
    rows, distinct = _rows(ctx.profile, h.node), _distinct(ctx.profile, h.node, h.column)
    ref_rows = [_rows(r, h.node) for r in ctx.references]
    ref_distinct = [_distinct(r, h.node, h.column) for r in ctx.references]
    if rows is None or distinct is None or None in ref_rows or None in ref_distinct:
        return [Check("key is profiled in this run and the references", False, "not profiled")]
    rr = [int(x) for x in ref_rows if x is not None]
    rd = [int(x) for x in ref_distinct if x is not None]
    unique = all(d >= NEAR_UNIQUE * r for d, r in zip(rd, rr, strict=True) if r)
    ceiling = max(rr) + max(cfg.volume_abs_margin, cfg.volume_rel_margin * max(rr))
    grew = rows > ceiling
    extra_rows = rows - statistics.median(rr)
    extra_keys = distinct - statistics.median(rd)
    flat = extra_rows > 0 and extra_keys < 0.5 * extra_rows
    return [
        Check("column is a key by name", is_key(h.column), h.column),
        Check(
            "key is unique in every reference run",
            unique,
            f"distinct/rows {min(d / r for d, r in zip(rd, rr, strict=True) if r):.3f}",
        ),
        Check("rows above the reference range", grew, f"{rows} rows, ceiling {ceiling:.0f}"),
        Check(
            "distinct keys did not grow with the rows",
            flat,
            f"+{extra_rows:g} rows, {extra_keys:+g} distinct keys",
        ),
    ]


def check_code(ctx: RunContext, group: Group, h: Hypothesis) -> list[Check]:
    node = ctx.project.nodes[h.node]
    commits = [c for c in changes_to(ctx, h.node) if c.hash == h.commit]
    files = [f for c in commits for f in c.files if file_matches(node.original_file_path, f)]
    checks = [Check("commit changed the model's file", bool(files), ", ".join(files) or "no")]
    if h.column:
        here = _at(group, h.node, h.column)
        checks.append(Check("the column itself is off", bool(here), f"{len(here)} symptoms"))
        upstream = {(r.node, r.column.lower()) for r in ctx.column_ancestors(h.node, h.column)}
        noisy = sorted(
            f"{s.node}.{s.column}"
            for s in group.symptoms
            if s.column and (s.node, s.column.lower()) in upstream
        )
        checks.append(
            Check("every input column is normal", not noisy, ", ".join(noisy) or "all normal")
        )
    else:
        here = _at(group, h.node, any_column=True)
        below = [i for i, s in enumerate(group.symptoms) if h.node in ctx.table_ancestors(s.node)]
        checks.append(
            Check(
                "the model or a model below it is off",
                bool(here or below),
                f"{len(here)} at the model, {len(below)} below",
            )
        )
    noisy_parents = sorted(p for p in ctx.parents(h.node) if _at(group, p, any_column=True))
    checks.append(
        Check(
            "every input table is normal",
            not noisy_parents,
            ", ".join(noisy_parents) or ", ".join(ctx.parents(h.node)) or "no inputs",
        )
    )
    return checks


def test(ctx: RunContext, group: Group, h: Hypothesis, cfg: MonitorConfig) -> Result:
    covered = explains(ctx, group, h)
    if h.kind == "source_table":
        own = [i for i in _at(group, h.node) if group.symptoms[i].column is None]
        checks = [Check("the table itself is off", bool(own), f"{len(own)} table-level symptoms")]
    elif h.kind == "source_column":
        own = _at(group, h.node, h.column)
        checks = [Check("the column itself is off", bool(own), f"{len(own)} symptoms")]
    elif h.kind == "duplicate_rows":
        own = _at(group, h.node, any_column=True)
        checks = check_duplicates(ctx, h, cfg)
    else:
        own = _at(group, h.node, h.column) if h.column else _at(group, h.node, any_column=True)
        checks = check_code(ctx, group, h)
    passed = all(c.passed for c in checks)
    strength, severity = _strength(group, own or covered)
    if h.kind in {"duplicate_rows", "code_change"} and passed:
        # A structural explanation: a repeated key, or code that changed under normal inputs.
        strength = 3 if own else 2
        severity = float("inf") if own else severity
    return Result(h, "observed" if passed else "failed", strength, severity, covered, tuple(checks))


def eliminate(ctx: RunContext, group: Group, results: Sequence[Result]) -> list[Result]:
    """Inferred causes for model columns that no observed cause explains."""
    explained = {i for r in results if r.passed for i in r.explains}
    candidates: dict[tuple[str, str], list[int]] = {}
    proofs: dict[tuple[str, str], list[Check]] = {}
    for i, s in enumerate(group.symptoms):
        if i in explained or not s.column or ctx.is_root(s.node):
            continue
        path = ctx.table_ancestors(s.node) | {s.node}
        changed = sorted(n for n in path if changes_to(ctx, n))
        if changed:
            continue
        roots = [r for r in ctx.column_ancestors(s.node, s.column) if ctx.is_root(r.node)]
        measured = [r for r in roots if is_measured(ctx.column_stats(r.node, r.column) or {})]
        noisy = [r for r in measured if _at(group, r.node, r.column)]
        unmeasured = sorted(r for r in roots if r not in measured)
        if noisy or not unmeasured:
            continue
        for ref in unmeasured:
            key = (ref.node, ref.column)
            candidates.setdefault(key, []).append(i)
            proofs[key] = [
                Check("no commit changed a model on the path", True, f"{len(path)} nodes checked"),
                Check(
                    "every measured input column is normal",
                    True,
                    ", ".join(f"{r.node}.{r.column}" for r in sorted(measured)) or "none measured",
                ),
                Check("this input has no distribution statistics", True, "text or boolean"),
            ]
    out = []
    for (node, column), idx in sorted(candidates.items()):
        h = Hypothesis("source_column", node, column)
        severity = max(group.symptoms[i].severity for i in idx)
        out.append(
            Result(h, "inferred", 0, severity, tuple(sorted(idx)), tuple(proofs[(node, column)]))
        )
    return out
