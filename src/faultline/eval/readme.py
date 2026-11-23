"""The README's result tables, written from eval/results/ only.

`faultline readme` rewrites the block between the two markers in README.md;
`faultline repro` checks the README still equals what this writes. Every number
links to the result file it comes from. Nothing is typed by hand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from faultline.eval.splits import FINAL_LABEL, FINAL_SPLIT, final_note

START = "<!-- results:start (written by `faultline readme`; do not edit by hand) -->"
END = "<!-- results:end -->"
SPLITS = ("dev", FINAL_SPLIT)
SPLIT_LABEL = {"dev": "dev", FINAL_SPLIT: FINAL_LABEL}

DIAGNOSIS = (
    ("dbt_tests", "dbt's own tests (alert only)"),
    ("dbt_tests_guess", "dbt tests + simple root-cause guess"),
    ("raw_log_llm.mlx_base", "local 7B model reading the raw log"),
    ("monitors", "faultline monitors (M4)"),
    ("triage", "**faultline triage (M5)**"),
)
ABLATIONS = (
    ("triage", "full deterministic triage"),
    ("triage.no_tests", "without the tests"),
    ("triage.no_lineage", "without lineage"),
)
SLOTS = (
    ("ranking", "triage", "rules only"),
    ("ranking", "triage_llm.mlx_base", "local 7B, base"),
    ("ranking", "triage_llm.mlx_ranker", "local 7B, fine-tuned on train"),
    ("ranking", "triage_llm.reference", "Claude Opus 5.5 (hosted reference)"),
    ("raw log", "raw_log_llm.mlx_base", "local 7B, base"),
    ("raw log", "raw_log_llm.mlx_raw_log", "local 7B, fine-tuned on train"),
    ("raw log", "raw_log_llm.reference", "Claude Opus 5.5 (hosted reference)"),
)


def _load(results: Path, split: str, name: str) -> dict[str, Any] | None:
    path = results / split / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def _cell(metric: dict[str, Any] | None, link: str) -> str:
    if not metric or metric.get("rate") is None:
        return "n/a"
    return f"[{metric['rate'] * 100:.1f}% ({metric['count']}/{metric['n']})]({link})"


def _link(results: Path, split: str, name: str) -> str:
    return f"{results.as_posix()}/{split}/{name}.md"


def diagnosis_table(results: Path) -> list[str]:
    lines = [
        "| Method | Split | Detected | Top-1 | Top-3 | Wrong top-1 | False alarms |",
        "|---|---|---|---|---|---|---|",
    ]
    for split in SPLITS:
        for name, label in DIAGNOSIS:
            doc = _load(results, split, name)
            if doc is None:
                continue
            f, c, link = (
                doc["metrics"]["faulted"],
                doc["metrics"]["clean"],
                _link(results, split, name),
            )
            lines.append(
                f"| {label} | {SPLIT_LABEL[split]} | {_cell(f['detected'], link)} | "
                f"{_cell(f['top1'], link)} | {_cell(f['top3'], link)} | "
                f"{_cell(f['wrong_top1'], link)} | {_cell(c['false_alarms'], link)} |"
            )
    return lines


def ablation_table(results: Path) -> list[str]:
    lines = ["| Variant | Split | Top-1 | Wrong top-1 |", "|---|---|---|---|"]
    for split in SPLITS:
        for name, label in ABLATIONS:
            doc = _load(results, split, name)
            if doc is None:
                continue
            f, link = doc["metrics"]["faulted"], _link(results, split, name)
            lines.append(
                f"| {label} | {SPLIT_LABEL[split]} | {_cell(f['top1'], link)} | "
                f"{_cell(f['wrong_top1'], link)} |"
            )
    return lines


def slots_table(results: Path, reference: bool) -> list[str]:
    lines = [
        "| Slot | Model | Split | Top-1 | Wrong top-1 | Cost per incident |",
        "|---|---|---|---|---|---|",
    ]
    for split in SPLITS:
        for slot, name, label in SLOTS:
            if name.endswith(".reference") != reference:
                continue
            doc = _load(results, split, name)
            if doc is None or "incomplete" in doc:
                continue
            f, link = doc["metrics"]["faulted"], _link(results, split, name)
            cost = doc.get("cost", {}).get("per_incident_usd")
            cost_text = "local" if cost is None else f"[${cost:.4f}]({link})"
            lines.append(
                f"| {slot} | {label} | {SPLIT_LABEL[split]} | {_cell(f['top1'], link)} | "
                f"{_cell(f['wrong_top1'], link)} | {cost_text} |"
            )
    return lines


def m7_table(results: Path) -> list[str]:
    lines = ["| What | Split | Result | False alarms on clean runs |", "|---|---|---|---|"]
    for split in SPLITS:
        fixes = _load(results, split, "fixes")
        if fixes:
            link, m = _link(results, split, "fixes"), fixes["metrics"]
            lines.append(
                f"| fix drafter: faults fixed (build passes, every model back to normal) | "
                f"{split} | {_cell(m['faulted']['fixed'], link)} | "
                f"{_cell(m['clean']['false_fixes'], link)} fixes proposed |"
            )
        tg = _load(results, split, "testgen")
        if tg:
            link, m = _link(results, split, "testgen"), tg["metrics"]
            lines.append(
                f"| generated tests: faults caught (mutation score) | {split} | "
                f"{_cell(m['faulted']['generated'], link)} vs the projects' own tests "
                f"{_cell(m['faulted']['own'], link)} | "
                f"{_cell(m['clean']['false_alarm_runs'], link)} |"
            )
    return lines


def final_commit(results: Path) -> str | None:
    runs = (
        sorted((results / FINAL_SPLIT).glob("*.run.json"))
        if (results / FINAL_SPLIT).is_dir()
        else []
    )
    commits = sorted({json.loads(p.read_text()).get("git_commit") or "" for p in runs} - {""})
    return ", ".join(c[:12] for c in commits) if commits else None


def render_tables(results: Path = Path("eval/results")) -> str:
    commit = final_commit(results)
    lines = [
        START,
        "",
        "### Finding the root cause",
        "",
        "Top-1: the first named cause is the right node (and column and commit, where the "
        "fault has one). Wrong top-1: a confident wrong answer. False alarms: clean runs "
        "flagged.",
        "",
        *diagnosis_table(results),
        "",
        "### What each part of triage is worth",
        "",
        *ablation_table(results),
        "",
        "### Language models in faultline's two model slots",
        "",
        "faultline, with a local model or none:",
        "",
        *slots_table(results, reference=False),
        "",
        "Reference line, a hosted model that is not part of faultline (CLAUDE.md principle 7):",
        "",
        *slots_table(results, reference=True),
        "",
        "### Fixes and generated tests",
        "",
        *m7_table(results),
        "",
        final_note(commit),
        "",
        END,
    ]
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    if START in text and END in text:
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        return head + block + tail
    return text.rstrip("\n") + "\n\n## Results\n\n" + block + "\n"
