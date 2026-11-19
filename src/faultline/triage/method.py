"""Triage as a method for `faultline eval`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from faultline.eval.loader import Incident
from faultline.eval.score import Prediction
from faultline.monitors.core import MonitorConfig, Profile, detect
from faultline.triage.agent import Triage
from faultline.triage.evidence import build_context


def triage_incident(
    incident: Incident, references: Sequence[Profile], config: MonitorConfig
) -> Triage:
    ctx, dbt = build_context(
        incident.incident_id,
        incident.run_dir,
        incident.profile,
        references,
        incident.history,
        incident.run_results,
    )
    anomalies = detect(incident.profile, references, config)
    return Triage(ctx, anomalies, dbt, config).run()


@dataclass
class TriageMethod:
    references: Mapping[str, Sequence[Profile]]
    config: MonitorConfig
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __call__(self, incident: Incident) -> Prediction:
        result = triage_incident(incident, self.references[incident.incident_id], self.config)
        self.reports[incident.incident_id] = result.report()
        return result.prediction()
