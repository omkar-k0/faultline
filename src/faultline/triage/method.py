"""Triage as a method for `faultline eval`, with its ablations."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from faultline.eval.loader import Incident
from faultline.eval.score import Prediction
from faultline.monitors.core import MonitorConfig, Profile, detect
from faultline.triage.agent import Reranker, Triage
from faultline.triage.evidence import RunContext, build_context

# Parts of triage an ablation can switch off. "llm_ranker" is off unless a
# re-ranker is given, so its ablation is the plain `triage` method.
ABLATIONS = ("tests", "lineage")


def without_lineage(ctx: RunContext) -> RunContext:
    """The same run with every lineage edge removed: tables and columns stand alone."""
    tables: Any = nx.DiGraph()
    tables.add_nodes_from(ctx.tables.nodes)
    return dataclasses.replace(ctx, tables=tables, columns=nx.DiGraph(), _index=None)


def triage_incident(
    incident: Incident,
    references: Sequence[Profile],
    config: MonitorConfig,
    ablate: str | None = None,
    reranker: Reranker | None = None,
) -> Triage:
    if ablate is not None and ablate not in ABLATIONS:
        raise ValueError(f"unknown ablation {ablate!r}; choose from {', '.join(ABLATIONS)}")
    ctx, dbt = build_context(
        incident.incident_id,
        incident.run_dir,
        incident.profile,
        references,
        incident.history,
        incident.run_results,
    )
    if ablate == "lineage":
        ctx = without_lineage(ctx)
    anomalies = detect(incident.profile, references, config)
    return Triage(ctx, anomalies, dbt, config, use_tests=ablate != "tests", reranker=reranker).run()


@dataclass
class TriageMethod:
    references: Mapping[str, Sequence[Profile]]
    config: MonitorConfig
    ablate: str | None = None
    reranker: Reranker | None = None
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)
    ungated: dict[str, Prediction] = field(default_factory=dict)

    def __call__(self, incident: Incident) -> Prediction:
        result = triage_incident(
            incident,
            self.references[incident.incident_id],
            self.config,
            self.ablate,
            self.reranker,
        )
        self.reports[incident.incident_id] = result.report()
        self.ungated[incident.incident_id] = result.ungated_prediction()
        return result.prediction()
