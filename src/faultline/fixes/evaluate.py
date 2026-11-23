"""Fix success rate on a split: triage, draft, rebuild, patch, build, compare.

For every faulted run: the deterministic triage names its top cause (from the
archived run, as in M5); the drafter proposes a fix for that cause; the run's
workspace is rebuilt exactly (inject/rebuild.py), the fix applied and dbt run.
The fix succeeds when the build passes and every model's profile equals the same
run built without its fault. Sources keep their bad data, since a fix in the
models cannot change them; everything the models produce must be back to normal.

Rate = fixed / faulted runs, so causes with no fix (and runs triage missed)
count against it. Clean runs are triaged too: any fix proposed there is a
false fix.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from faultline.collectors.dbt_artifacts import load_project
from faultline.eval.loader import load_incidents
from faultline.eval.run import FAULT_ORDER, _git_commit, harness_references
from faultline.eval.score import load_truth
from faultline.fixes.draft import Fix, draft
from faultline.inject.rebuild import load_truth_doc, rebuild
from faultline.inject.run import profile_diff, run_dbt
from faultline.monitors.core import load_monitor_config
from faultline.triage.method import triage_incident


@dataclass(frozen=True)
class FixOutcome:
    incident_id: str
    fault_type: str
    cause: str | None
    pattern: str
    reason: str
    proposed: bool
    build_ok: bool | None = None
    still_off: tuple[str, ...] = ()
    fixed: bool = False
    diff: str = ""


def _top_cause(report: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for incident in report.get("incidents", []):
        if incident["causes"]:
            return incident["causes"][0], incident
    return None


def try_fix(
    truth: dict[str, Any], run_dir: str, report: dict[str, Any], projects_dir: str
) -> FixOutcome:
    """Draft and test one fix. Runs in a worker process: two dbt builds."""
    fault_type = (truth.get("fault") or {}).get("type") or "clean"
    top = _top_cause(report)
    if top is None:
        return FixOutcome(
            truth["incident_id"], fault_type, None, "none", "no confirmed cause", False
        )
    cause, incident = top
    project = load_project(Path(run_dir).parent, target=Path(run_dir).name)
    with tempfile.TemporaryDirectory() as tmp:
        built = rebuild(truth, Path(tmp) / "fault", Path(projects_dir))
        fix: Fix = draft(built.workspace, project, cause, incident)
        if not fix.proposed:
            return FixOutcome(
                truth["incident_id"], fault_type, fix.cause, fix.pattern, fix.reason, False
            )
        diff = fix.diff(built.workspace)
        for path, content in fix.files.items():
            (built.workspace / path).write_text(content)
        fixed_run = run_dbt(built.workspace)
        clean = rebuild(truth, Path(tmp) / "clean", Path(projects_dir), clean=True)
        clean_run = run_dbt(clean.workspace)
    still_off = tuple(
        n for n in profile_diff(clean_run.profile, fixed_run.profile) if n.startswith("model.")
    )
    return FixOutcome(
        truth["incident_id"],
        fault_type,
        fix.cause,
        fix.pattern,
        fix.reason,
        True,
        fixed_run.build_ok,
        still_off,
        fixed_run.build_ok and not still_off,
        diff,
    )


def _rate(count: int, n: int) -> dict[str, Any]:
    return {"count": count, "n": n, "rate": round(count / n, 4) if n else None}


def summarise(outcomes: Sequence[FixOutcome]) -> dict[str, Any]:
    faulted = [o for o in outcomes if o.fault_type != "clean"]
    clean = [o for o in outcomes if o.fault_type == "clean"]
    by_type: dict[str, Any] = {}
    for ft in FAULT_ORDER:
        rows = [o for o in faulted if o.fault_type == ft]
        if rows:
            by_type[ft] = {
                "n": len(rows),
                "proposed": _rate(sum(o.proposed for o in rows), len(rows)),
                "fixed": _rate(sum(o.fixed for o in rows), len(rows)),
            }
    proposed = [o for o in faulted if o.proposed]
    return {
        "faulted": {
            "n": len(faulted),
            "proposed": _rate(len(proposed), len(faulted)),
            "fixed": _rate(sum(o.fixed for o in faulted), len(faulted)),
            "fixed_when_proposed": _rate(sum(o.fixed for o in proposed), len(proposed)),
        },
        "clean": {
            "n": len(clean),
            "false_fixes": _rate(sum(o.proposed for o in clean), len(clean)),
        },
        "by_fault_type": by_type,
        "by_pattern": {
            p: _rate(
                sum(o.fixed for o in proposed if o.pattern == p),
                sum(o.pattern == p for o in proposed),
            )
            for p in sorted({o.pattern for o in proposed})
        },
    }


def _pct(m: dict[str, Any]) -> str:
    return "n/a" if m["rate"] is None else f"{m['rate'] * 100:.1f}% ({m['count']}/{m['n']})"


def to_markdown(doc: dict[str, Any]) -> str:
    m = doc["metrics"]
    lines = [
        f"# Fix drafter on {doc['split']}",
        "",
        f"Command `{doc['command']}`. A fix succeeds when dbt build passes and every model "
        "equals the same run built without its fault.",
        "",
        "| Fault type | n | Fix proposed | Fixed |",
        "|---|---|---|---|",
    ]
    for ft, r in m["by_fault_type"].items():
        lines.append(f"| {ft} | {r['n']} | {_pct(r['proposed'])} | {_pct(r['fixed'])} |")
    f = m["faulted"]
    lines += [
        f"| **all faulted** | {f['n']} | {_pct(f['proposed'])} | {_pct(f['fixed'])} |",
        "",
        f"Fixed when a fix was proposed: {_pct(f['fixed_when_proposed'])}. "
        f"Fixes proposed on clean runs: {_pct(m['clean']['false_fixes'])}.",
        "",
        "| Pattern | Fixed / proposed |",
        "|---|---|",
        *[f"| {p} | {_pct(r)} |" for p, r in m["by_pattern"].items()],
    ]
    return "\n".join(lines) + "\n"


def evaluate(
    split: str,
    benchmark_dir: Path = Path("benchmark"),
    projects_dir: Path = Path("projects"),
    results_dir: Path = Path("eval/results"),
    config_path: Path = Path("faultline.toml"),
    workers: int = 2,
    download: bool = True,
) -> dict[str, Any]:
    incidents, section = load_incidents(split, benchmark_dir, download=download)
    truths = {i.incident_id: load_truth(benchmark_dir, split, i.incident_id) for i in incidents}
    refs = harness_references(incidents, truths)
    config = load_monitor_config(config_path)
    jobs = []
    for incident in incidents:
        report = triage_incident(incident, refs[incident.incident_id], config).report()
        truth = load_truth_doc(benchmark_dir, split, incident.incident_id)
        jobs.append((truth, str(incident.run_dir), report, str(projects_dir)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(try_fix, *zip(*jobs, strict=True)))
    outcomes.sort(key=lambda o: o.incident_id)
    doc = {
        "split": split,
        "command": f"faultline fix eval --split {split}",
        "archive_sha256": section["archive_sha256"],
        "metrics": summarise(outcomes),
        "incidents": [asdict(o) for o in outcomes],
    }
    out = results_dir / split
    out.mkdir(parents=True, exist_ok=True)
    (out / "fixes.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    (out / "fixes.md").write_text(to_markdown(doc))
    (out / "fixes.run.json").write_text(json.dumps({"git_commit": _git_commit()}, indent=1) + "\n")
    return doc
