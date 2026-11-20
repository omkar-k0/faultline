"""Fine-tuning data for faultline's two LLM slots, from the train split only.

`faultline finetune export --slot ranker|raw_log` writes chat-format JSONL for
`mlx_lm.lora` (train.jsonl, valid.jsonl) under build/finetune/<slot>/. Only
benchmark/train/ is read; any other split is refused. The prompts are built by
the same code the eval uses, so the model is trained on exactly what it will
see. Labels come from the train ground truth.

Ranker slot: each training incident's surviving causes, as the re-ranker sees
them. The answer puts the causes that match the truth (location level, as in
scoring) first and keeps the rest in rule order. Each incident also appears with
its causes shuffled, so the model learns to judge causes, not positions. The
summary is a fixed template built from the true cause, so nothing is invented.

Raw-log slot: the raw-log prompt of every train run. The answer names the true
root cause only when the log shows something to go on: a failed or errored dbt
node, or a commit that changed a model. Otherwise the label is "no incident",
because that is all the log supports. Training a model to name a cause it
cannot see would teach it to guess.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faultline.eval import baselines
from faultline.eval.loader import Incident, load_incidents
from faultline.eval.run import harness_references
from faultline.eval.score import Location, Truth, load_truth, matches
from faultline.monitors.core import MonitorConfig
from faultline.triage import llm_rank
from faultline.triage.agent import Triage, rerank_inputs
from faultline.triage.hypotheses import changes_to
from faultline.triage.method import triage_incident

SLOTS = ("ranker", "raw_log")
TRAIN_SPLIT = "train"
SHUFFLES = 2  # extra orders per incident with two or more causes
VALID_SHARE = 0.10


@dataclass(frozen=True)
class Example:
    incident_id: str
    system: str
    user: str
    answer: str

    def line(self) -> str:
        return json.dumps(
            {
                "messages": [
                    {"role": "system", "content": self.system},
                    {"role": "user", "content": self.user},
                    {"role": "assistant", "content": self.answer},
                ]
            },
            sort_keys=True,
        )


def is_valid(incident_id: str) -> bool:
    """About 10% of incidents, chosen by hash, validate the adapter; the rest train it."""
    digest = hashlib.sha256(incident_id.encode()).digest()
    return digest[0] < int(256 * VALID_SHARE)


def _location(cause: dict[str, Any]) -> Location:
    return Location(node=cause["node"], column=cause["column"], commit=cause["commit"])


def ranker_answer(causes: Sequence[dict[str, Any]], truth: Truth) -> str | None:
    """Truth-matching causes first, the rest in the order given. None when none match."""
    hits = [i for i, c in enumerate(causes) if matches(_location(c), truth)]
    if not hits:
        return None
    order = hits + [i for i in range(len(causes)) if i not in hits]
    best = causes[hits[0]]
    summary = (
        f"Most likely: {best['description']}. It passed every test and explains "
        f"{len(best['explains'])} of the incident's symptoms."
    )
    return json.dumps({"order": [i + 1 for i in order], "summary": summary})


def ranker_examples(triage: Triage, truth: Truth) -> Iterator[Example]:
    rng = random.Random(triage.ctx.run_id)
    for report in triage.reports:
        incident, causes = rerank_inputs(report)
        if not causes:
            continue
        orders = [list(range(len(causes)))]
        for _ in range(SHUFFLES if len(causes) > 1 else 0):
            order = list(range(len(causes)))
            rng.shuffle(order)
            if order not in orders:
                orders.append(order)
        for order in orders:
            shown = [causes[i] for i in order]
            answer = ranker_answer(shown, truth)
            if answer is None:
                break  # the truth is not among this incident's survivors
            yield Example(
                triage.ctx.run_id,
                llm_rank.SYSTEM_PROMPT,
                llm_rank.build_prompt(incident, shown),
                answer,
            )


def log_shows_something(incident: Incident, triage: Triage) -> bool:
    """A failed or errored dbt node, or a commit that changed a model."""
    if baselines.detect_dbt(incident):
        return True
    return any(changes_to(triage.ctx, n) for n in triage.ctx.project.nodes)


def raw_log_answer(incident: Incident, triage: Triage, truth: Truth) -> str:
    if truth.clean or not log_shows_something(incident, triage):
        return json.dumps({"incident": False, "not_confirmed": False, "root_causes": []})
    return json.dumps(
        {
            "incident": True,
            "not_confirmed": False,
            "root_causes": [{"node": truth.node, "column": truth.column, "commit": truth.commit}],
        }
    )


def export(
    slot: str,
    out_dir: Path,
    config: MonitorConfig,
    benchmark_dir: Path = Path("benchmark"),
    split: str = TRAIN_SPLIT,
    download: bool = True,
) -> dict[str, Any]:
    if split != TRAIN_SPLIT:
        raise ValueError(f"fine-tuning reads {TRAIN_SPLIT} only, not {split!r}")
    if slot not in SLOTS:
        raise ValueError(f"unknown slot {slot!r}; choose from {', '.join(SLOTS)}")
    incidents, section = load_incidents(split, benchmark_dir, download=download)
    truths = {i.incident_id: load_truth(benchmark_dir, split, i.incident_id) for i in incidents}
    references = harness_references(incidents, truths)
    train: list[Example] = []
    valid: list[Example] = []
    for incident in incidents:
        truth = truths[incident.incident_id]
        triage = triage_incident(incident, references[incident.incident_id], config)
        if slot == "ranker":
            examples = list(ranker_examples(triage, truth))
        else:
            examples = [
                Example(
                    incident.incident_id,
                    baselines.SYSTEM_PROMPT,
                    baselines.build_prompt(incident),
                    raw_log_answer(incident, triage, truth),
                )
            ]
        (valid if is_valid(incident.incident_id) else train).extend(examples)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, rows in (("train", train), ("valid", valid)):
        text = "".join(e.line() + "\n" for e in rows)
        (out_dir / f"{name}.jsonl").write_text(text)
        files[name] = {
            "examples": len(rows),
            "incidents": len({e.incident_id for e in rows}),
            "sha256": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
        }
    manifest = {
        "slot": slot,
        "split": split,
        "archive_sha256": section["archive_sha256"],
        "prompt_sha256": (
            llm_rank.prompt_sha256() if slot == "ranker" else baselines.prompt_sha256()
        ),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest
