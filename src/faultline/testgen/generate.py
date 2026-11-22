"""Propose dbt tests from what is always true in clean runs.

Input: profiles of known-good runs of one project. No fault is ever seen. For each
relation, every fact that held in all of them becomes a check:

- row count stays within the seen range (plus 1% and at least one row)
- a column that was never null stays never null; otherwise its null share stays at
  most the highest seen plus 5 points
- a key column (by name) that was unique stays unique
- a numeric column stays within the seen min and max, widened by half the span on
  each side, and its average stays near the seen averages (at least 20% slack)
- a date or time column of a seed or source stays within the seen range, plus an
  hour. Models are left out: some build a calendar up to the day they run.
- a text column with at most 50 values keeps a distinct count near the seen range

Each relation gets one dbt singular test that returns the names of its failed
checks, with severity "warn", so a failing check never stops the build or skips
anything downstream. Distinct counts in the profiles are approximate, so ranges on
them are widened by 10%.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from faultline.collectors.dbt_artifacts import Project
from faultline.monitors.core import Profile, is_key

TEST_DIR = "tests/faultline_generated"
ROWS_MARGIN = 0.01
NULL_MARGIN = 0.05
RANGE_MARGIN = 0.50  # of the seen span; 0.10 cried wolf on small resampled tables (dev)
MEAN_MARGIN = 0.20  # of the mean, at least
DISTINCT_MAX = 50
UNIQUE_FLOOR = 0.99  # distinct/rows in every reference, approximate counts


@dataclass(frozen=True)
class Check:
    name: str
    condition: str  # SQL, true when the check fails; __REL__ stands for the relation


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _num(x: float) -> str:
    return repr(float(x))


def relation_ref(project: Project, node_id: str) -> str | None:
    node = project.nodes.get(node_id)
    if node is None:
        return None
    if node.resource_type in {"model", "seed", "snapshot"}:
        return f"{{{{ ref('{node.name}') }}}}"
    if node.resource_type == "source":
        parts = node_id.split(".")
        if len(parts) >= 4:
            return f"{{{{ source('{parts[2]}', '{parts[3]}') }}}}"
    return None


def _column_checks(
    node_kind: str, col: str, stats: Sequence[dict[str, Any]], rows: Sequence[int]
) -> list[Check]:
    c = _q(col)
    out: list[Check] = []
    shares = [1 - s["non_null"] / r if r else 0.0 for s, r in zip(stats, rows, strict=True)]
    if all(s["non_null"] == r for s, r in zip(stats, rows, strict=True)) and min(rows) > 0:
        out.append(Check(f"not_null:{col}", f"exists (select 1 from __REL__ where {c} is null)"))
    elif max(shares) + NULL_MARGIN < 1:
        hi = max(shares) + NULL_MARGIN
        out.append(
            Check(
                f"null_share:{col}",
                f"(select avg(case when {c} is null then 1.0 else 0.0 end) from __REL__) "
                f"> {_num(hi)}",
            )
        )
    if is_key(col) and all(
        r and s.get("distinct", 0) >= UNIQUE_FLOOR * r for s, r in zip(stats, rows, strict=True)
    ):
        out.append(
            Check(
                f"unique:{col}",
                f"exists (select {c} from __REL__ where {c} is not null group by {c} "
                "having count(*) > 1)",
            )
        )
    if all(s.get("mean") is not None for s in stats):
        lo = min(float(s["min"]) for s in stats)
        hi = max(float(s["max"]) for s in stats)
        pad = RANGE_MARGIN * (hi - lo) or RANGE_MARGIN * abs(hi) or 1e-9
        means = [float(s["mean"]) for s in stats]
        m_lo, m_hi = min(means), max(means)
        m_pad = max(RANGE_MARGIN * (m_hi - m_lo), MEAN_MARGIN * max(abs(m_lo), abs(m_hi))) or 1e-9
        if all(math.isfinite(x) for x in (lo, hi, m_lo, m_hi)):
            out.append(
                Check(
                    f"range:{col}",
                    f"exists (select 1 from __REL__ where {c} < {_num(lo - pad)} "
                    f"or {c} > {_num(hi + pad)})",
                )
            )
            out.append(
                Check(
                    f"mean:{col}",
                    f"(select avg({c}) from __REL__) not between {_num(m_lo - m_pad)} "
                    f"and {_num(m_hi + m_pad)}",
                )
            )
    elif node_kind in {"seed", "source"} and all(
        isinstance(s.get("min"), str) and isinstance(s.get("max"), str) for s in stats
    ):
        lo, hi = min(s["min"] for s in stats), max(s["max"] for s in stats)
        out.append(
            Check(
                f"time_range:{col}",
                f"exists (select 1 from __REL__ where cast({c} as timestamp) < "
                f"timestamp '{lo}' - interval 1 hour or cast({c} as timestamp) > "
                f"timestamp '{hi}' + interval 1 hour)",
            )
        )
    elif (
        all(s.get("min") is None for s in stats)
        and max(s.get("distinct", 0) for s in stats) <= DISTINCT_MAX
    ):
        lo = min(s.get("distinct", 0) for s in stats)
        hi = max(s.get("distinct", 0) for s in stats)
        if hi > 0:
            low, high = math.floor(lo * 0.9) - 1, math.ceil(hi * 1.1) + 1
            out.append(
                Check(
                    f"distinct:{col}",
                    f"(select count(distinct {c}) from __REL__) "
                    f"not between {max(low, 0)} and {high}",
                )
            )
    return out


def learn(project: Project, references: Sequence[Profile]) -> dict[str, list[Check]]:
    """Checks per relation, from facts true in every reference profile."""
    out: dict[str, list[Check]] = {}
    nodes = sorted(set.intersection(*(set(p) for p in references))) if references else []
    for node_id in nodes:
        entries = [p[node_id] for p in references]
        if any(e.get("missing") or e.get("error") or "rows" not in e for e in entries):
            continue
        node = project.nodes.get(node_id)
        if node is None or node.resource_type not in {"model", "seed", "source"}:
            continue
        rows = [int(e["rows"]) for e in entries]
        pad = max(1, math.ceil(ROWS_MARGIN * max(rows)))
        checks = [
            Check(
                "rows",
                f"(select count(*) from __REL__) not between {max(min(rows) - pad, 0)} "
                f"and {max(rows) + pad}",
            )
        ]
        cols = sorted(set.intersection(*(set(e.get("columns", {})) for e in entries)))
        for col in cols:
            stats = [e["columns"][col] for e in entries]
            checks += _column_checks(node.resource_type, col, stats, rows)
        out[node_id] = checks
    return out


def test_name(project: Project, node_id: str) -> str:
    node = project.nodes[node_id]
    kind = {"model": "m", "seed": "s", "source": "src"}[node.resource_type]
    return f"faultline_gen_{kind}_{node.name}"


def to_dbt_tests(project: Project, checks: dict[str, list[Check]]) -> dict[str, str]:
    """{path: sql} singular tests, one per relation; each row returned is a failed check."""
    files: dict[str, str] = {}
    for node_id, node_checks in sorted(checks.items()):
        ref = relation_ref(project, node_id)
        if ref is None or not node_checks:
            continue
        parts = [
            f"select '{c.name}' as failed_check where {c.condition.replace('__REL__', ref)}"
            for c in node_checks
        ]
        files[f"{TEST_DIR}/{test_name(project, node_id)}.sql"] = (
            "-- Generated by faultline from clean runs only. Each row returned is a failed check.\n"
            "{{ config(severity='warn', tags=['faultline_generated']) }}\n"
            + "\nunion all\n".join(parts)
            + "\n"
        )
    return files
