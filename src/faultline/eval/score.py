"""Score predictions against ground truth, at location level.

A candidate location matches when:
- its node is the truth's node, or the physical node written to (for stripe the
  models read a source while the change sits in its seed: same relation);
- and its column equals the truth's column, when the truth names one;
- and, for code faults, its commit is the truth's commit (7+ character prefix).
Matching the fault type alone never counts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOP_K = 3


@dataclass(frozen=True)
class Location:
    node: str
    column: str | None = None
    commit: str | None = None


@dataclass(frozen=True)
class Prediction:
    """`detected` with no candidates means "not confirmed": an incident, cause unknown."""

    detected: bool
    candidates: tuple[Location, ...] = ()

    @property
    def abstained(self) -> bool:
        return self.detected and not self.candidates


@dataclass(frozen=True)
class Truth:
    incident_id: str
    project: str
    fault_type: str | None  # None for a clean run
    fault_class: str | None
    node: str | None
    physical: str | None
    column: str | None
    commit: str | None

    @property
    def clean(self) -> bool:
        return self.fault_type is None


def load_truth(benchmark_dir: Path, split: str, incident_id: str) -> Truth:
    doc = json.loads((benchmark_dir / split / incident_id / "truth.json").read_text())
    fault = doc.get("fault") or {}
    loc = doc.get("location") or {}
    return Truth(
        incident_id=doc["incident_id"],
        project=doc["project"],
        fault_type=fault.get("type"),
        fault_class=fault.get("class"),
        node=loc.get("node"),
        physical=loc.get("physical"),
        column=loc.get("column"),
        commit=loc.get("commit"),
    )


def matches_node(candidate: Location, truth: Truth) -> bool:
    """Diagnostic only: the node is right, column and commit ignored."""
    return not truth.clean and candidate.node in {truth.node, truth.physical}


def matches(candidate: Location, truth: Truth) -> bool:
    if truth.clean:
        return False
    if candidate.node not in {truth.node, truth.physical}:
        return False
    if truth.column is not None and (candidate.column or "").lower() != truth.column.lower():
        return False
    if truth.fault_class == "code":
        commit = candidate.commit or ""
        if len(commit) < 7 or not (truth.commit or "").startswith(commit):
            return False
    return True


@dataclass(frozen=True)
class Outcome:
    incident_id: str
    project: str
    fault_type: str  # "clean" for clean runs
    detected: bool
    hit_rank: int | None  # 1-based rank of the first matching candidate within top-k
    node_hit_rank: int | None  # diagnostic: same, matching the node only
    abstained: bool
    wrong_top1: bool  # a first candidate was given and it is wrong
    false_alarm: bool


def score_incident(prediction: Prediction, truth: Truth) -> Outcome:
    if truth.clean:
        return Outcome(
            truth.incident_id,
            truth.project,
            "clean",
            prediction.detected,
            None,
            None,
            prediction.abstained,
            False,
            prediction.detected,
        )
    hit = node_hit = None
    if prediction.detected:
        for rank, cand in enumerate(prediction.candidates[:TOP_K], start=1):
            if hit is None and matches(cand, truth):
                hit = rank
            if node_hit is None and matches_node(cand, truth):
                node_hit = rank
    wrong_top1 = prediction.detected and bool(prediction.candidates) and hit != 1
    return Outcome(
        truth.incident_id,
        truth.project,
        truth.fault_type or "",
        prediction.detected,
        hit,
        node_hit,
        prediction.abstained,
        wrong_top1,
        False,
    )


def _rate(count: int, n: int) -> dict[str, Any]:
    return {"count": count, "n": n, "rate": round(count / n, 4) if n else None}


def _faulted_metrics(outcomes: list[Outcome]) -> dict[str, Any]:
    n = len(outcomes)
    return {
        "n": n,
        "detected": _rate(sum(o.detected for o in outcomes), n),
        "top1": _rate(sum(o.hit_rank == 1 for o in outcomes), n),
        "top3": _rate(sum(o.hit_rank is not None for o in outcomes), n),
        "wrong_top1": _rate(sum(o.wrong_top1 for o in outcomes), n),
        "not_confirmed": _rate(sum(o.abstained for o in outcomes), n),
        "diagnostic_node_top1": _rate(sum(o.node_hit_rank == 1 for o in outcomes), n),
        "diagnostic_node_top3": _rate(sum(o.node_hit_rank is not None for o in outcomes), n),
    }


def aggregate(outcomes: Iterable[Outcome]) -> dict[str, Any]:
    items = list(outcomes)
    faulted = [o for o in items if o.fault_type != "clean"]
    clean = [o for o in items if o.fault_type == "clean"]
    by_type = {
        ft: _faulted_metrics([o for o in faulted if o.fault_type == ft])
        for ft in sorted({o.fault_type for o in faulted})
    }
    by_project = {
        p: _faulted_metrics([o for o in faulted if o.project == p])
        for p in sorted({o.project for o in faulted})
    }
    return {
        "faulted": _faulted_metrics(faulted),
        "clean": {
            "n": len(clean),
            "false_alarms": _rate(sum(o.false_alarm for o in clean), len(clean)),
        },
        "by_fault_type": by_type,
        "by_project": by_project,
    }
