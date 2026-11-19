"""Group: join symptoms that are connected through lineage into incidents.

Two symptoms belong to the same incident when one sits on the other's node or
upstream of it in table lineage. Ten alarms downstream of one broken source
are one incident, not ten. Groups are ordered by size, then by name, so the
result is deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from faultline.triage.evidence import RunContext, Symptom


@dataclass(frozen=True)
class Group:
    number: int  # 1-based, after ordering
    symptoms: tuple[Symptom, ...]

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(sorted({s.node for s in self.symptoms}))


def group_symptoms(ctx: RunContext, symptoms: Sequence[Symptom]) -> list[Group]:
    nodes = sorted({s.node for s in symptoms})
    parent = {n: n for n in nodes}

    def find(n: str) -> str:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for node in nodes:
        ancestors = ctx.table_ancestors(node)
        for other in nodes:
            if other != node and other in ancestors:
                ra, rb = find(node), find(other)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)

    buckets: dict[str, list[Symptom]] = {}
    for s in symptoms:
        buckets.setdefault(find(s.node), []).append(s)
    ordered = sorted(buckets.values(), key=lambda b: (-len(b), min(s.node for s in b)))
    return [Group(i, tuple(b)) for i, b in enumerate(ordered, start=1)]
