"""The triage agent: a plain, explicit state machine. No agent framework.

    GATHER -> GROUP -> PROPOSE -> TEST -> RANK -> REPORT -> DONE

With a ranker:  ... -> RANK -> RERANK -> REPORT

GATHER   symptoms of the run: monitor anomalies and failed dbt tests or models.
GROUP    symptoms joined by lineage into incidents (`incidents.manager`).
PROPOSE  candidate causes upstream of each incident's symptoms.
TEST     each candidate against the evidence; then causes by elimination.
RANK     the survivors only, deterministically. Never pads the list.
RERANK   optional: a local language model reorders the survivors and writes a
         summary. It sees only the survivors and their evidence, and its answer
         is checked: it can drop no cause and add none.
REPORT   up to three causes per incident with their evidence, or "not confirmed".

Ablations (docs/EVAL.md) switch parts off: `use_tests=False` ranks every
proposed cause, tested or not; the no-lineage ablation strips the lineage
graphs from the context before triage starts (see `method.py`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from faultline.eval.score import TOP_K, Location, Prediction
from faultline.incidents.manager import Group, group_symptoms
from faultline.monitors.core import Anomaly, MonitorConfig, is_key
from faultline.triage.checks import Result, eliminate, test
from faultline.triage.evidence import RunContext, Symptom, from_anomaly
from faultline.triage.hypotheses import Hypothesis, propose

RERANK_LIMIT = 6  # survivors shown to a re-ranker, at most


class State(Enum):
    GATHER = "gather"
    GROUP = "group"
    PROPOSE = "propose"
    TEST = "test"
    RANK = "rank"
    RERANK = "rerank"
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
    tested: list[Result] = field(default_factory=list)  # every proposed cause, with its test
    ranked: list[Result] = field(default_factory=list)
    failed: list[Result] = field(default_factory=list)
    summary: str | None = None
    rerank: dict[str, Any] | None = None

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
            **({"summary": self.summary} if self.summary is not None else {}),
            **({"rerank": self.rerank} if self.rerank is not None else {}),
        }


# A re-ranker gets one incident's survivors (as report dicts) and returns the
# order it prefers, as indices into that list, plus a short summary.
Reranker = Callable[[dict[str, Any], list[dict[str, Any]]], tuple[list[int], str, dict[str, Any]]]


def _locations(results: Sequence[Result]) -> list[Location]:
    seen: set[Location] = set()
    out: list[Location] = []
    for r in results:
        h = r.hypothesis
        loc = Location(node=h.node, column=h.column, commit=h.commit)
        if loc not in seen:
            seen.add(loc)
            out.append(loc)
    return out


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
    use_tests: bool = True
    reranker: Reranker | None = None
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
                report.tested = [test(self.ctx, report.group, h, self.config) for h in hyps]
                if self.use_tests:
                    inferred = eliminate(self.ctx, report.group, report.tested)
                    report.ranked = report.tested + inferred  # filtered in RANK
                    report.failed = [r for r in report.tested if not r.passed]
            self.state = State.RANK
        elif self.state is State.RANK:
            for report in self.reports:
                report.ranked = (
                    rank(report.ranked) if self.use_tests else sorted(report.tested, key=rank_key)
                )
            self.reports.sort(
                key=lambda r: (
                    not r.ranked,
                    rank_key(r.ranked[0]) if r.ranked else (),
                    r.group.number,
                )
            )
            self.state = State.RERANK if self.reranker else State.REPORT
        elif self.state is State.RERANK:
            assert self.reranker is not None
            for report in self.reports:
                if report.ranked:
                    self._rerank(report, self.reranker)
            self.state = State.REPORT
        elif self.state is State.REPORT:
            self.state = State.DONE
        return self.state

    def run(self) -> Triage:
        while self.state is not State.DONE:
            self.step()
        return self

    def _rerank(self, report: IncidentReport, reranker: Reranker) -> None:
        """Let the ranker reorder the survivors. Its answer can only permute them."""
        shown = report.ranked[:RERANK_LIMIT]
        incident = {k: v for k, v in report.as_dict().items() if k != "causes"}
        order, summary, info = reranker(incident, [r.as_dict(report.group) for r in shown])
        valid = [i for i in dict.fromkeys(order) if 0 <= i < len(shown)]
        kept = valid + [i for i in range(len(shown)) if i not in valid]
        report.ranked = [shown[i] for i in kept] + report.ranked[RERANK_LIMIT:]
        report.summary = summary
        report.rerank = {**info, "order": valid, "completed_by_rule": len(kept) - len(valid)}

    def prediction(self) -> Prediction:
        if not self.symptoms:
            return Prediction(detected=False)
        out = _locations([r for report in self.reports for r in report.ranked])
        return Prediction(detected=True, candidates=tuple(out[:TOP_K]))

    def ungated_prediction(self) -> Prediction:
        """What triage would answer with every proposed cause ranked, tested or not."""
        if not self.symptoms:
            return Prediction(detected=False)
        reports = sorted(
            (r for r in self.reports if r.tested),
            key=lambda r: (min(rank_key(t) for t in r.tested), r.group.number),
        )
        ordered = [t for r in reports for t in sorted(r.tested, key=rank_key)]
        return Prediction(detected=True, candidates=tuple(_locations(ordered)[:TOP_K]))

    def report(self) -> dict[str, Any]:
        return {
            "run": self.ctx.run_id,
            "states": self.trace,
            "detected": bool(self.symptoms),
            "incidents": [r.as_dict() for r in self.reports],
        }
