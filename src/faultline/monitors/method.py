"""Monitors as a detection method for `faultline eval`."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from faultline.eval.loader import Incident
from faultline.eval.score import TOP_K, Location, Prediction
from faultline.monitors.core import Anomaly, MonitorConfig, Profile, detect


def pick_references(
    incident_ids: Sequence[str], project_of: Mapping[str, str], clean_ids: Sequence[str]
) -> dict[str, list[str]]:
    """Known-good history for every incident: all but one clean run of its project.

    A clean run leaves itself out; a faulted run leaves out one clean run chosen
    by a hash of its id. Every incident therefore gets the same number of
    reference runs, so the reference reveals nothing about the incident.
    """
    by_project: dict[str, list[str]] = {}
    for cid in sorted(clean_ids):
        by_project.setdefault(project_of[cid], []).append(cid)
    refs: dict[str, list[str]] = {}
    for iid in incident_ids:
        pool = by_project.get(project_of[iid], [])
        if iid in pool:
            drop = iid
        elif pool:
            drop = pool[int(hashlib.sha256(iid.encode()).hexdigest(), 16) % len(pool)]
        else:
            drop = None
        refs[iid] = [c for c in pool if c != drop]
    return refs


def _depths(manifest: Mapping[str, Any]) -> dict[str, int]:
    parents: Mapping[str, list[str]] = manifest.get("parent_map", {})
    memo: dict[str, int] = {}

    def depth(node: str, seen: frozenset[str]) -> int:
        if node not in memo:
            ups = [p for p in parents.get(node, []) if p not in seen]
            memo[node] = 0 if not ups else 1 + max(depth(p, seen | {node}) for p in ups)
        return memo[node]

    for node in parents:
        depth(node, frozenset())
    return memo


def rank(anomalies: Sequence[Anomaly], manifest: Mapping[str, Any]) -> tuple[Location, ...]:
    """Most upstream anomalies first, then the most severe; one per node and column."""
    depth = _depths(manifest)
    ordered = sorted(
        anomalies, key=lambda a: (depth.get(a.node, 99), -a.severity, a.node, a.column or "")
    )
    seen: set[tuple[str, str | None]] = set()
    out: list[Location] = []
    for a in ordered:
        key = (a.node, a.column)
        if key not in seen:
            seen.add(key)
            out.append(Location(node=a.node, column=a.column))
    return tuple(out[:TOP_K])


@dataclass
class MonitorMethod:
    references: Mapping[str, Sequence[Profile]]
    config: MonitorConfig
    anomalies: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def __call__(self, incident: Incident) -> Prediction:
        found = detect(incident.profile, self.references[incident.incident_id], self.config)
        self.anomalies[incident.incident_id] = [
            {**asdict(a), "severity": a.severity if a.severity != float("inf") else "inf"}
            for a in found
        ]
        if not found:
            return Prediction(detected=False)
        return Prediction(detected=True, candidates=rank(found, incident.manifest or {}))
