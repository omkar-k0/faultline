"""Baselines faultline is compared against.

- `dbt_tests`: alert only. An incident is flagged when the build errors or any
  dbt test fails or warns. No root cause.
- `dbt_tests_guess`: same alert, plus a naive root cause: the nodes (and
  columns) of failing tests and the nodes that errored, upstream first.
- `raw_log_llm`: the dbt log, run results, cleaned git history and the list of
  node ids go to a local language model, which answers in strict JSON.

Every baseline sees an `Incident` only, never ground truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from faultline.eval.loader import Incident
from faultline.eval.score import TOP_K, Location, Prediction
from faultline.llm.client import LLMClient

ALERT_STATUSES = frozenset({"error", "fail", "warn", "runtime error"})


def _failing(incident: Incident) -> list[dict[str, Any]]:
    results = (incident.run_results or {}).get("results", [])
    return [r for r in results if str(r.get("status", "")).lower() in ALERT_STATUSES]


def detect_dbt(incident: Incident) -> bool:
    """Flag when dbt left no results (the build died) or anything failed or warned."""
    if incident.run_results is None:
        return True
    return bool(_failing(incident))


def baseline_dbt_tests(incident: Incident) -> Prediction:
    return Prediction(detected=detect_dbt(incident))


def _depths(manifest: dict[str, Any]) -> dict[str, int]:
    """Longest distance from a root for every node in the manifest's parent map."""
    parents: dict[str, list[str]] = manifest.get("parent_map", {})
    memo: dict[str, int] = {}

    def depth(node: str, seen: frozenset[str]) -> int:
        if node in memo:
            return memo[node]
        ups = [p for p in parents.get(node, []) if p not in seen]
        value = 0 if not ups else 1 + max(depth(p, seen | {node}) for p in ups)
        memo[node] = value
        return value

    for node in parents:
        depth(node, frozenset())
    return memo


def baseline_dbt_tests_guess(incident: Incident) -> Prediction:
    if not detect_dbt(incident):
        return Prediction(detected=False)
    manifest = incident.manifest or {}
    nodes = {**manifest.get("nodes", {}), **manifest.get("sources", {})}
    depth = _depths(manifest)
    found: list[tuple[int, int, Location]] = []
    for order, result in enumerate(_failing(incident)):
        uid = str(result.get("unique_id", ""))
        node = nodes.get(uid, {})
        if uid.startswith("test."):
            target = node.get("attached_node") or next(
                (
                    d
                    for d in node.get("depends_on", {}).get("nodes", [])
                    if not d.startswith("test.")
                ),
                None,
            )
            if not target:
                continue
            loc = Location(node=target, column=node.get("column_name"))
        else:
            loc = Location(node=uid)
        found.append((depth.get(loc.node, 99), order, loc))
    seen: set[tuple[str, str | None]] = set()
    candidates: list[Location] = []
    for _d, _o, loc in sorted(found, key=lambda item: (item[0], item[1])):
        key = (loc.node, (loc.column or "").lower() or None)
        if key not in seen:
            seen.add(key)
            candidates.append(loc)
    return Prediction(detected=True, candidates=tuple(candidates[:TOP_K]))


# ------------------------------------------------------------------ raw-log LLM

SYSTEM_PROMPT = """You diagnose failed or suspicious dbt pipeline runs.
You get the dbt log, the run results, the recent git history and the list of nodes.
Decide whether this run has a data incident. If it does, name up to 3 likely root
causes, most likely first. A root cause is a node id from the list, optionally a
column, and for a code change the commit hash. If you cannot tell the cause, say so.
Answer with one JSON object and nothing else:
{"incident": true or false,
 "not_confirmed": true or false,
 "root_causes": [{"node": "<node id>",
                  "column": "<column or null>",
                  "commit": "<hash or null>"}]}"""

LOG_CHAR_BUDGET = 16_000
_IMPORTANT = re.compile(r"error|fail|warn|exception|done\.|completed", re.IGNORECASE)


def trim_log(log: str, budget: int = LOG_CHAR_BUDGET) -> str:
    """Non-debug lines; error and warning lines first, then the rest, within the budget."""
    lines = [ln for ln in log.splitlines() if "[debug]" not in ln and ln.strip()]
    important = [ln for ln in lines if _IMPORTANT.search(ln)]
    rest = [ln for ln in lines if not _IMPORTANT.search(ln)]
    out: list[str] = []
    size = 0
    for ln in important + rest:
        if size + len(ln) + 1 > budget:
            break
        out.append(ln)
        size += len(ln) + 1
    keep = set(out)
    return "\n".join(ln for ln in lines if ln in keep)


def build_prompt(incident: Incident) -> str:
    results = (incident.run_results or {}).get("results", [])
    summary = [
        f"{r.get('unique_id')}: {r.get('status')}"
        + (
            f" ({str(r.get('message'))[:200]})"
            if r.get("status") not in {"success", "pass"}
            else ""
        )
        for r in results
        if r.get("status") not in {"success", "pass"}
    ]
    manifest = incident.manifest or {}
    node_ids = sorted(
        [
            u
            for u, n in manifest.get("nodes", {}).items()
            if n.get("resource_type") in {"model", "seed", "snapshot"}
        ]
        + list(manifest.get("sources", {}))
    )
    history = [f"{c.message} {c.hash}: " + ", ".join(c.files[:20]) for c in incident.history]
    return "\n\n".join(
        [
            "## dbt log (trimmed)\n" + trim_log(incident.dbt_log),
            "## run results that did not succeed\n" + ("\n".join(summary) or "none"),
            "## git history, oldest first\n" + ("\n".join(history) or "none"),
            "## node ids\n" + "\n".join(node_ids),
        ]
    )


def parse_answer(text: str) -> Prediction:
    """Strict JSON answer to a Prediction. Anything unreadable counts as abstaining."""
    start, end = text.find("{"), text.rfind("}")
    try:
        doc = json.loads(text[start : end + 1]) if start != -1 and end > start else None
    except json.JSONDecodeError:
        doc = None
    if not isinstance(doc, dict):
        return Prediction(detected=True)
    if doc.get("incident") is False:
        return Prediction(detected=False)
    if doc.get("not_confirmed") is True:
        return Prediction(detected=True)
    candidates = []
    for item in doc.get("root_causes") or []:
        if isinstance(item, dict) and isinstance(item.get("node"), str):
            column = item.get("column")
            commit = item.get("commit")
            candidates.append(
                Location(
                    node=item["node"],
                    column=column if isinstance(column, str) and column.lower() != "null" else None,
                    commit=commit if isinstance(commit, str) and commit.lower() != "null" else None,
                )
            )
    return Prediction(detected=True, candidates=tuple(candidates[:TOP_K]))


def prompt_sha256() -> str:
    return "sha256:" + hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()


@dataclass
class RawLogLLM:
    client: LLMClient
    raw_answers: dict[str, str] = field(default_factory=dict)

    def __call__(self, incident: Incident) -> Prediction:
        answer = self.client.complete(SYSTEM_PROMPT, build_prompt(incident))
        self.raw_answers[incident.incident_id] = answer
        return parse_answer(answer)


Baseline = Callable[[Incident], Prediction]
NO_LLM_BASELINES: dict[str, Baseline] = {
    "dbt_tests": baseline_dbt_tests,
    "dbt_tests_guess": baseline_dbt_tests_guess,
}
BASELINES = (*NO_LLM_BASELINES, "raw_log_llm", "monitors")
