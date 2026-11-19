"""Run a baseline on a split, score it, and write the result files.

Writes three files under eval/results/<split>/:
- <baseline>.json: config, config hash, archive hash, every prediction and
  outcome, and the metrics. Deterministic for the no-LLM baselines.
- <baseline>.md: the table.
- <baseline>.run.json: when and from which commit it ran (changes every run).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from faultline import __version__
from faultline.eval.baselines import NO_LLM_BASELINES, Baseline, RawLogLLM, prompt_sha256
from faultline.eval.loader import load_incidents
from faultline.eval.score import Prediction, aggregate, load_truth, score_incident
from faultline.llm.client import LLMClient
from faultline.monitors.core import MONITORS, MonitorConfig, load_monitor_config
from faultline.monitors.method import MonitorMethod, pick_references

FAULT_ORDER = (
    "schema_change",
    "late_or_missing_data",
    "duplicate_keys",
    "null_spike",
    "distribution_shift",
    "model_logic_bug",
    "broken_join",
    "timezone_error",
)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def config_for(
    baseline: str, client: LLMClient | None, monitor_config: MonitorConfig | None = None
) -> dict[str, Any]:
    config: dict[str, Any] = {"baseline": baseline, "faultline_version": __version__}
    if baseline == "monitors":
        assert monitor_config is not None
        config["monitors"] = asdict(monitor_config)
        config["reference"] = "other clean runs of the same project in the split, all but one"
    if baseline == "raw_log_llm":
        assert client is not None
        cfg = getattr(client, "config", None)
        config.update(
            {
                "model": client.model,
                "prompt_sha256": prompt_sha256(),
                "temperature": getattr(cfg, "temperature", None),
                "seed": getattr(cfg, "seed", None),
            }
        )
    return config


def _pct(metric: dict[str, Any]) -> str:
    rate = metric.get("rate")
    return "n/a" if rate is None else f"{rate * 100:.1f}% ({metric['count']}/{metric['n']})"


def to_markdown(doc: dict[str, Any]) -> str:
    m = doc["metrics"]
    lines = [
        f"# {doc['baseline']} on {doc['split']}",
        "",
        f"Config hash `{doc['config_hash']}` · archive `{doc['archive_sha256'][:19]}…` · "
        f"command `{doc['command']}`",
        "",
        "| Fault type | n | Detected | Top-1 | Top-3 | Wrong top-1 | Not confirmed |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = [(ft, m["by_fault_type"][ft]) for ft in FAULT_ORDER if ft in m["by_fault_type"]]
    rows.append(("**all faulted**", m["faulted"]))
    for name, r in rows:
        lines.append(
            f"| {name} | {r['n']} | {_pct(r['detected'])} | {_pct(r['top1'])} | "
            f"{_pct(r['top3'])} | {_pct(r['wrong_top1'])} | {_pct(r['not_confirmed'])} |"
        )
    if "by_monitor" in doc:
        bm = doc["by_monitor"]
        types = [ft for ft in FAULT_ORDER if ft in m["by_fault_type"]]
        lines += [
            "",
            "## Which monitor fired (incidents per fault type)",
            "",
            "| Monitor | " + " | ".join(types) + " | clean (false alarms) |",
            "|---|" + "---|" * (len(types) + 1),
        ]
        for mon in MONITORS:
            row = bm.get(mon, {})
            cells = [str(row.get(ft, 0)) for ft in types] + [str(row.get("clean", 0))]
            lines.append(f"| {mon} | " + " | ".join(cells) + " |")
    lines += [
        "",
        f"False alarms on clean runs: {_pct(m['clean']['false_alarms'])}.",
        "",
        "Diagnostic, not a score: right node at top-1 "
        f"{_pct(m['faulted']['diagnostic_node_top1'])}, in top-3 "
        f"{_pct(m['faulted']['diagnostic_node_top3'])} (column and commit ignored).",
        "",
        "Top-1 and top-3 count a root cause only at location level: node, column where the "
        "truth has one, commit for code faults. See docs/EVAL.md.",
        "",
    ]
    return "\n".join(lines)


def run_eval(
    split: str,
    baseline: str,
    *,
    benchmark_dir: Path = Path("benchmark"),
    dist_dir: Path = Path("dist"),
    runs_dir: Path = Path("build/eval"),
    results_dir: Path = Path("eval/results"),
    client: LLMClient | None = None,
    download: bool = True,
    command: str | None = None,
    config_path: Path = Path("faultline.toml"),
) -> dict[str, Any]:
    incidents, section = load_incidents(split, benchmark_dir, dist_dir, runs_dir, download)
    raw: RawLogLLM | None = None
    monitor_method: MonitorMethod | None = None
    monitor_config: MonitorConfig | None = None
    truths = {i.incident_id: load_truth(benchmark_dir, split, i.incident_id) for i in incidents}
    if baseline == "monitors":
        # The harness, not the method, picks known-good history from ground truth.
        monitor_config = load_monitor_config(config_path)
        by_id = {i.incident_id: i for i in incidents}
        ref_ids = pick_references(
            [i.incident_id for i in incidents],
            {i.incident_id: i.project for i in incidents},
            [iid for iid, t in truths.items() if t.clean],
        )
        references = {iid: [by_id[r].profile for r in refs] for iid, refs in ref_ids.items()}
        monitor_method = MonitorMethod(references, monitor_config)
        method: Baseline = monitor_method
    elif baseline in NO_LLM_BASELINES:
        method = NO_LLM_BASELINES[baseline]
    elif baseline == "raw_log_llm":
        if client is None:
            raise ValueError("raw_log_llm needs an LLM client")
        raw = RawLogLLM(client)
        method = raw
    else:
        raise ValueError(f"unknown method {baseline!r}")

    config = config_for(baseline, client, monitor_config)
    config_hash = hashlib.sha256(
        json.dumps({**config, "archive_sha256": section["archive_sha256"]}, sort_keys=True).encode()
    ).hexdigest()[:12]

    rows = []
    outcomes = []
    for incident in incidents:
        prediction: Prediction = method(incident)
        truth = truths[incident.incident_id]
        outcome = score_incident(prediction, truth)
        outcomes.append(outcome)
        row: dict[str, Any] = {
            "incident_id": incident.incident_id,
            "prediction": {
                "detected": prediction.detected,
                "candidates": [asdict(c) for c in prediction.candidates],
            },
            "outcome": asdict(outcome),
        }
        if raw is not None:
            row["raw_answer"] = raw.raw_answers.get(incident.incident_id)
        if monitor_method is not None:
            row["anomalies"] = monitor_method.anomalies.get(incident.incident_id, [])
        rows.append(row)

    doc = {
        "split": split,
        "baseline": baseline,
        "command": command or f"faultline eval --split {split} --baseline {baseline}",
        "config": config,
        "config_hash": config_hash,
        "archive_sha256": section["archive_sha256"],
        "plan_sha256": section.get("plan_sha256"),
        "metrics": aggregate(outcomes),
        "incidents": rows,
    }
    if monitor_method is not None:
        by_monitor: dict[str, dict[str, int]] = {}
        for row, outcome in zip(rows, outcomes, strict=True):
            for mon in sorted({a["monitor"] for a in row["anomalies"]}):
                cell = by_monitor.setdefault(mon, {})
                cell[outcome.fault_type] = cell.get(outcome.fault_type, 0) + 1
        doc["by_monitor"] = by_monitor
    out_dir = results_dir / split
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{baseline}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    (out_dir / f"{baseline}.md").write_text(to_markdown(doc))
    run_info = {
        "git_commit": _git_commit(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config_hash": config_hash,
    }
    (out_dir / f"{baseline}.run.json").write_text(json.dumps(run_info, indent=1) + "\n")
    return doc
