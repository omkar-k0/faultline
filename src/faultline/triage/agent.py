"""The triage agent: a plain, explicit state machine. No agent framework.

    GATHER -> GROUP -> PROPOSE -> TEST -> RANK -> REPORT -> DONE

GATHER   symptoms of the run: monitor anomalies and failed dbt tests or models.
GROUP    symptoms joined by lineage into incidents (`incidents.manager`).
PROPOSE  candidate causes upstream of each incident's symptoms.
TEST     each candidate against the evidence; then causes by elimination.
RANK     the survivors only, deterministically. Never pads the list.
REPORT   up to three causes per incident with their evidence, or "not confirmed".

Nothing here calls a language model. An optional LLM re-ranker (M5b) may
reorder the survivors and write prose; it can never add a cause.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from faultline.eval.score import TOP_K, Location, Prediction
from faultline.incidents.manager import Group, group_symptoms
from faultline.monitors.core import Anomaly, MonitorConfig, is_key
from faultline.triage.checks import Result, eliminate, test
from faultline.triage.evidence import RunContext, Symptom, from_anomaly
from faultline.triage.hypotheses import Hypothesis, propose


class State(Enum):
    GATHER = "gather"
    GROUP = "group"
    PROPOSE = "propose"
    TEST = "test"
    RANK = "rank"
    REPORT = "report"
    DONE = "done"


def rank_key(r: Result) -> tuple[Any, ...]:
    h = r.hypothesis
    return (
        -r.strength,
        h.column is None,  # a named column is the more precise cause
        -len(r.explains),
        -r.severity,
        bool(h.column and is_key(h.column)) if r.mode == "inferred" else False,
        h.sort_key(),
    )


def rank(results: Sequence[Result]) -> list[Result]:
    return sorted((r for r in results if r.passed), key=rank_key)


@dataclass
class IncidentReport:
    group: Group
    proposed: int = 0
    ranked: list[Result] = field(default_factory=list)
    failed: list[Result] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "confirmed" if self.ranked else "not_confirmed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "incident": self.group.number,
            "status": self.status,
            "symptoms": [s.as_dict() for s in self.group.symptoms],
            "proposed": self.proposed,
            "rejected": len(self.failed),
            "causes": [r.as_dict(self.group) for r in self.ranked[:TOP_K]],
        }


@dataclass
class Triage:
    ctx: RunContext
    anomalies: Sequence[Anomaly]
    dbt: Sequence[Symptom]
    config: MonitorConfig
    state: State = State.GATHER
    trace: list[str] = field(default_factory=list)
    symptoms: list[Symptom] = field(default_factory=list)
    reports: list[IncidentReport] = field(default_factory=list)
    _proposals: list[list[Hypothesis]] = field(default_factory=list, repr=False)

    def step(self) -> State:
        self.trace.append(self.state.value)
        if self.state is State.GATHER:
            self.symptoms = [from_anomaly(a) for a in self.anomalies] + list(self.dbt)
            self.state = State.GROUP
        elif self.state is State.GROUP:
            self.reports = [IncidentReport(g) for g in group_symptoms(self.ctx, self.symptoms)]
            self.state = State.PROPOSE
        elif self.state is State.PROPOSE:
            self._proposals = [propose(self.ctx, r.group) for r in self.reports]
            for report, hyps in zip(self.reports, self._proposals, strict=True):
                report.proposed = len(hyps)
            self.state = State.TEST
        elif self.state is State.TEST:
            for report, hyps in zip(self.reports, self._proposals, strict=True):
                results = [test(self.ctx, report.group, h, self.config) for h in hyps]
                results += eliminate(self.ctx, report.group, results)
                report.ranked = results  # filtered in RANK
                report.failed = [r for r in results if not r.passed]
            self.state = State.RANK
        elif self.state is State.RANK:
            for report in self.reports:
                report.ranked = rank(report.ranked)
            self.reports.sort(
                key=lambda r: (
                    not r.ranked,
                    rank_key(r.ranked[0]) if r.ranked else (),
                    r.group.number,
                )
            )
            self.state = State.REPORT
        elif self.state is State.REPORT:
            self.state = State.DONE
        return self.state

    def run(self) -> Triage:
        while self.state is not State.DONE:
            self.step()
        return self

    def prediction(self) -> Prediction:
        if not self.symptoms:
            return Prediction(detected=False)
        seen: set[Location] = set()
        out: list[Location] = []
        for report in self.reports:
            for r in report.ranked:
                h = r.hypothesis
                loc = Location(node=h.node, column=h.column, commit=h.commit)
                if loc not in seen:
                    seen.add(loc)
                    out.append(loc)
        return Prediction(detected=True, candidates=tuple(out[:TOP_K]))

    def report(self) -> dict[str, Any]:
        return {
            "run": self.ctx.run_id,
            "states": self.trace,
            "detected": bool(self.symptoms),
            "incidents": [r.as_dict() for r in self.reports],
        }
