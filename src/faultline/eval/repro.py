"""`faultline repro`: check every number in eval/results/ from a clean clone.

1. Deterministic results (no model) are re-run into a scratch folder and must match
   the committed files byte for byte.
2. Results that needed a model (local or hosted) cannot be re-run without it. Their
   stored predictions are scored again against the ground truth, and the metrics
   must equal the committed ones; the config hash in the .md must match the .json.
3. Fix and generated-test results are summarised again from their stored per-run
   outcomes. Re-running them in full needs about 160 dbt builds:
   `make eval-dev-fixes eval-dev-testgen`.
4. The README tables must equal what `faultline readme` writes from these files.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from faultline.eval.run import run_eval
from faultline.eval.score import Location, Prediction, aggregate, load_truth, score_incident
from faultline.eval.splits import FINAL_SPLIT

DETERMINISTIC = (
    ("dbt_tests", None),
    ("dbt_tests_guess", None),
    ("monitors", None),
    ("triage", None),
    ("triage", "tests"),
    ("triage", "lineage"),
)


@dataclass
class Report:
    ok: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def check(self, label: str, passed: bool, detail: str = "") -> None:
        (self.ok if passed else self.failed).append(label + (f": {detail}" if detail else ""))


def _name(baseline: str, ablate: str | None) -> str:
    return f"{baseline}.no_{ablate}" if ablate else baseline


def rerun_deterministic(results: Path, report: Report, log: Callable[[str], None]) -> None:
    for split_dir in sorted(p for p in results.iterdir() if p.is_dir()):
        split = split_dir.name
        for baseline, ablate in DETERMINISTIC:
            name = _name(baseline, ablate)
            committed = split_dir / f"{name}.json"
            if not committed.exists():
                continue
            log(f"re-running {split}/{name}")
            with tempfile.TemporaryDirectory() as tmp:
                run_eval(
                    split,
                    baseline,
                    results_dir=Path(tmp),
                    ablate=ablate,
                    allow_final=split == FINAL_SPLIT,
                )
                fresh = (Path(tmp) / split / f"{name}.json").read_bytes()
            report.check(f"{split}/{name}.json re-run", fresh == committed.read_bytes())


def rescore_model_results(results: Path, benchmark_dir: Path, report: Report) -> None:
    deterministic = {_name(b, a) for b, a in DETERMINISTIC}
    for path in sorted(results.glob("*/*.json")):
        if path.name.endswith(".run.json") or path.stem in deterministic:
            continue
        doc: dict[str, Any] = json.loads(path.read_text())
        if "metrics" not in doc or "incidents" not in doc or "config_hash" not in doc:
            continue
        split = path.parent.name
        outcomes = []
        for row in doc["incidents"]:
            pred = row["prediction"]
            prediction = Prediction(
                pred["detected"], tuple(Location(**c) for c in pred["candidates"])
            )
            outcomes.append(
                score_incident(prediction, load_truth(benchmark_dir, split, row["incident_id"]))
            )
        report.check(f"{split}/{path.stem} re-scored", aggregate(outcomes) == doc["metrics"])
        md = path.with_suffix(".md")
        report.check(
            f"{split}/{path.stem} config hash",
            md.exists() and doc["config_hash"] in md.read_text(),
        )


def resummarise_m7(results: Path, report: Report) -> None:
    from dataclasses import fields

    from faultline.fixes.evaluate import FixOutcome
    from faultline.fixes.evaluate import summarise as fix_summary
    from faultline.testgen.evaluate import summarise as tg_summary

    for path in sorted(results.glob("*/fixes.json")):
        doc = json.loads(path.read_text())
        names = {f.name for f in fields(FixOutcome)}
        rows = []
        for r in doc["incidents"]:
            kwargs: dict[str, Any] = {k: v for k, v in r.items() if k in names}
            kwargs["still_off"] = tuple(kwargs.get("still_off", ()))
            rows.append(FixOutcome(**kwargs))
        report.check(f"{path.parent.name}/fixes summarised", fix_summary(rows) == doc["metrics"])
    for path in sorted(results.glob("*/testgen.json")):
        doc = json.loads(path.read_text())
        report.check(
            f"{path.parent.name}/testgen summarised", tg_summary(doc["incidents"]) == doc["metrics"]
        )


def repro(
    results: Path = Path("eval/results"),
    benchmark_dir: Path = Path("benchmark"),
    readme: Path = Path("README.md"),
    log: Callable[[str], None] = print,
) -> Report:
    from faultline.eval.readme import render_tables, replace_block

    report = Report()
    rerun_deterministic(results, report, log)
    rescore_model_results(results, benchmark_dir, report)
    resummarise_m7(results, report)
    text = readme.read_text()
    report.check("README tables", replace_block(text, render_tables(results)) == text)
    return report
