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
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from faultline import __version__
from faultline.eval.baselines import NO_LLM_BASELINES, Baseline, RawLogLLM, prompt_sha256
from faultline.eval.loader import Incident, load_incidents
from faultline.eval.score import (
    Outcome,
    Prediction,
    Truth,
    _rate,
    aggregate,
    load_truth,
    score_incident,
)
from faultline.llm.client import LLMClient
from faultline.monitors.core import MONITORS, MonitorConfig, Profile, load_monitor_config
from faultline.monitors.method import MonitorMethod, pick_references
from faultline.triage import llm_rank
from faultline.triage.method import ABLATIONS, TriageMethod

# Methods that compare a run with known-good runs picked by the harness.
REFERENCE_METHODS = frozenset({"monitors", "triage", "triage_llm"})
TRIAGE_METHODS = frozenset({"triage", "triage_llm"})
LLM_METHODS = frozenset({"raw_log_llm", "triage_llm"})

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


def harness_references(
    incidents: Sequence[Incident], truths: Mapping[str, Truth]
) -> dict[str, list[Profile]]:
    """Known-good profiles for every incident, picked by the harness from ground truth.

    Only which runs are clean is read from the truth files; the method never sees them.
    """
    by_id = {i.incident_id: i for i in incidents}
    ref_ids = pick_references(
        [i.incident_id for i in incidents],
        {i.incident_id: i.project for i in incidents},
        [iid for iid, t in truths.items() if t.clean],
    )
    return {iid: [by_id[r].profile for r in refs] for iid, refs in ref_ids.items()}


def result_name(baseline: str, ablate: str | None = None, variant: str | None = None) -> str:
    name = f"{baseline}.no_{ablate}" if ablate else baseline
    return f"{name}.{variant}" if variant else name


def _adapter_sha256(adapter: str | None) -> str | None:
    """Hash of a LoRA adapter's weights, so a result names exactly what was served."""
    if not adapter:
        return None
    weights = Path(adapter) / "adapters.safetensors"
    if not weights.exists():
        return None
    return "sha256:" + hashlib.sha256(weights.read_bytes()).hexdigest()


def config_for(
    baseline: str,
    client: LLMClient | None,
    monitor_config: MonitorConfig | None = None,
    ablate: str | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {"baseline": baseline, "faultline_version": __version__}
    if ablate:
        config["ablate"] = ablate
    if baseline in REFERENCE_METHODS:
        assert monitor_config is not None
        config["monitors"] = asdict(monitor_config)
        config["reference"] = "other clean runs of the same project in the split, all but one"
    if baseline == "triage":
        config["triage"] = "deterministic ranking, no language model"
    if baseline == "triage_llm":
        config["triage"] = "deterministic tests, survivors re-ranked by a local language model"
    if baseline in {"raw_log_llm", "triage_llm"}:
        assert client is not None
        cfg = getattr(client, "config", None)
        config.update(
            {
                "model": client.model,
                "prompt_sha256": (
                    prompt_sha256() if baseline == "raw_log_llm" else llm_rank.prompt_sha256()
                ),
                "temperature": getattr(cfg, "temperature", None),
                "seed": getattr(cfg, "seed", None),
            }
        )
        public = getattr(cfg, "public", None)
        if callable(public):
            config["reference_line"] = public()  # hosted model; never the key
        for attr in ("profile", "served_model", "adapter"):
            if getattr(cfg, attr, None):
                config[attr] = getattr(cfg, attr)
        if getattr(cfg, "adapter", None):
            config["adapter_sha256"] = _adapter_sha256(cfg.adapter)  # type: ignore[union-attr]
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
    if "gating" in doc:
        g = doc["gating"]
        lines += [
            "",
            "## The gate",
            "",
            f"- Answered (a cause given): {g['answered']} of {g['detected']} detected faulted "
            f"runs; right at top-1 when answering: {_pct(g['right_when_answering'])}.",
            f"- Not confirmed: {g['not_confirmed']}; correct not confirmed: "
            f"{_pct(g['correct_not_confirmed'])} (abstained, and the best untested cause "
            "would have been wrong).",
            f"- Without the tests (every proposed cause ranked) top-1 would be "
            f"{_pct(g['ungated_top1'])}.",
        ]
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
    ablate: str | None = None,
    variant: str | None = None,
    write: bool = True,
) -> dict[str, Any]:
    """Score one method on one split. `variant` labels a model profile or the reference
    line in the result's name; `write=False` scores without writing (dry runs)."""
    if ablate is not None and (baseline != "triage" or ablate not in ABLATIONS):
        raise ValueError(f"--ablate {ablate} applies to --baseline triage only ({ABLATIONS})")
    if variant is not None and baseline not in LLM_METHODS:
        raise ValueError(f"a model variant applies to {sorted(LLM_METHODS)} only")
    name = result_name(baseline, ablate, variant)
    incidents, section = load_incidents(split, benchmark_dir, dist_dir, runs_dir, download)
    raw: RawLogLLM | None = None
    monitor_method: MonitorMethod | None = None
    triage_method: TriageMethod | None = None
    monitor_config: MonitorConfig | None = None
    truths = {i.incident_id: load_truth(benchmark_dir, split, i.incident_id) for i in incidents}
    if baseline in REFERENCE_METHODS:
        # The harness, not the method, picks known-good history from ground truth.
        monitor_config = load_monitor_config(config_path)
        references = harness_references(incidents, truths)
        method: Baseline
        if baseline == "monitors":
            monitor_method = MonitorMethod(references, monitor_config)
            method = monitor_method
        else:
            reranker = None
            if baseline == "triage_llm":
                if client is None:
                    raise ValueError("triage_llm needs an LLM client")
                reranker = llm_rank.LLMReranker(client)
            triage_method = TriageMethod(references, monitor_config, ablate, reranker)
            method = triage_method
    elif baseline in NO_LLM_BASELINES:
        method = NO_LLM_BASELINES[baseline]
    elif baseline == "raw_log_llm":
        if client is None:
            raise ValueError("raw_log_llm needs an LLM client")
        raw = RawLogLLM(client)
        method = raw
    else:
        raise ValueError(f"unknown method {baseline!r}")

    config = config_for(baseline, client, monitor_config, ablate)
    config_hash = hashlib.sha256(
        json.dumps({**config, "archive_sha256": section["archive_sha256"]}, sort_keys=True).encode()
    ).hexdigest()[:12]

    rows = []
    outcomes = []
    ungated_outcomes = []
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
        if triage_method is not None:
            row["report"] = triage_method.reports.get(incident.incident_id)
            ungated = score_incident(triage_method.ungated[incident.incident_id], truth)
            ungated_outcomes.append(ungated)
            row["ungated_hit_rank"] = ungated.hit_rank
        rows.append(row)

    doc = {
        "split": split,
        "baseline": name,
        "command": command
        or f"faultline eval --split {split} --baseline {baseline}"
        + (f" --ablate {ablate}" if ablate else ""),
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
    if triage_method is not None:
        doc["gating"] = gating(outcomes, ungated_outcomes)
    cost_summary = getattr(client, "cost_summary", None)
    if callable(cost_summary):
        doc["cost"] = cost_summary(len(incidents))
    if not write:
        return doc
    out_dir = results_dir / split
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    (out_dir / f"{name}.md").write_text(to_markdown(doc))
    run_info = {
        "git_commit": _git_commit(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "config_hash": config_hash,
    }
    (out_dir / f"{name}.run.json").write_text(json.dumps(run_info, indent=1) + "\n")
    if triage_method is not None:
        write_ablation_table(out_dir)
    if baseline in LLM_METHODS or baseline == "triage":
        write_llm_slots_table(out_dir)
    return doc


def gating(outcomes: Sequence[Outcome], ungated: Sequence[Outcome]) -> dict[str, Any]:
    """What the tests did: answers given, abstentions, and whether abstaining was right."""
    pairs = [(o, u) for o, u in zip(outcomes, ungated, strict=True) if o.fault_type != "clean"]
    detected = [(o, u) for o, u in pairs if o.detected]
    answered = [o for o, _ in detected if not o.abstained]
    abstained = [u for o, u in detected if o.abstained]
    return {
        "detected": len(detected),
        "answered": len(answered),
        "right_when_answering": _rate(sum(o.hit_rank == 1 for o in answered), len(answered)),
        "not_confirmed": len(abstained),
        "correct_not_confirmed": _rate(sum(u.hit_rank != 1 for u in abstained), len(abstained)),
        "ungated_top1": _rate(sum(u.hit_rank == 1 for _, u in pairs), len(pairs)),
    }


ABLATION_ROWS = (
    ("triage_llm", "full: tests, lineage, LLM re-ranker"),
    ("triage", "no LLM ranker (deterministic ranking)"),
    ("triage.no_tests", "no tests (every proposed cause ranked)"),
    ("triage.no_lineage", "no lineage (causes only at alarmed tables)"),
)


def write_ablation_table(out_dir: Path) -> None:
    """One table from whichever triage result files exist in the split's folder."""
    split = out_dir.name
    lines = [
        f"# Triage ablations on {split}",
        "",
        "Built from the result files in this folder; a row is missing until its run exists.",
        "",
        "| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | Correct not confirmed | "
        "False alarms | File |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, label in ABLATION_ROWS:
        path = out_dir / f"{name}.json"
        if not path.exists():
            continue
        doc = json.loads(path.read_text())
        f, g = doc["metrics"]["faulted"], doc.get("gating", {})
        ncc = g.get("correct_not_confirmed", {"rate": None})
        lines.append(
            f"| {label} | {_pct(f['top1'])} | {_pct(f['top3'])} | {_pct(f['wrong_top1'])} | "
            f"{_pct(f['not_confirmed'])} | {_pct(ncc)} | "
            f"{_pct(doc['metrics']['clean']['false_alarms'])} | [{name}.md]({name}.md) |"
        )
    (out_dir / "ablations.md").write_text("\n".join(lines) + "\n")


LOCAL_SLOT_ROWS = {
    "ranking (triage)": (
        ("triage", "rules only, no model"),
        ("triage_llm", "base, Ollama"),
        ("triage_llm.mlx_base", "base, MLX"),
        ("triage_llm.mlx_ranker", "tuned on train, MLX"),
    ),
    "raw-log baseline": (
        ("raw_log_llm", "base, Ollama"),
        ("raw_log_llm.mlx_base", "base, MLX"),
        ("raw_log_llm.mlx_raw_log", "tuned on train, MLX"),
    ),
}
REFERENCE_SLOT_ROWS = {
    "ranking (triage)": "triage_llm.reference",
    "raw-log baseline": "raw_log_llm.reference",
}


def _slot_row(out_dir: Path, name: str, label: str) -> str | None:
    path = out_dir / f"{name}.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    f = doc["metrics"]["faulted"]
    cost = doc.get("cost", {}).get("per_incident_usd")
    cost_text = "local" if "cost" not in doc else f"${cost:.4f}"
    return (
        f"| {label} | {_pct(f['top1'])} | {_pct(f['top3'])} | {_pct(f['wrong_top1'])} | "
        f"{_pct(f['not_confirmed'])} | {_pct(doc['metrics']['clean']['false_alarms'])} | "
        f"{cost_text} | [{name}.md]({name}.md) |"
    )


def write_llm_slots_table(out_dir: Path) -> None:
    """Base vs tuned vs reference per LLM slot, from whichever result files exist."""
    head = (
        "| Variant | Top-1 | Top-3 | Wrong top-1 | Not confirmed | False alarms | "
        "Cost per incident | File |\n|---|---|---|---|---|---|---|---|"
    )
    lines = [
        f"# The two LLM slots on {out_dir.name}",
        "",
        "Built from the result files in this folder; a row is missing until its run exists.",
        "The hosted reference line is listed apart from faultline's own local results "
        "(CLAUDE.md principle 7).",
    ]
    for slot, rows in LOCAL_SLOT_ROWS.items():
        lines += ["", f"## {slot}", "", "faultline, local models:", "", head]
        lines += [r for n, label in rows if (r := _slot_row(out_dir, n, label))]
        ref = _slot_row(out_dir, REFERENCE_SLOT_ROWS[slot], "Claude, hosted (reference)")
        lines += ["", "Reference line, hosted, not part of faultline:", "", head]
        lines.append(ref or "| not run yet |  |  |  |  |  |  |  |")
    (out_dir / "llm_slots.md").write_text("\n".join(lines) + "\n")
