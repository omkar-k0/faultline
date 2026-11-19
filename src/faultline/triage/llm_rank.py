"""Optional re-ranker: the local language model orders the survivors.

The model sees one incident at a time: its symptoms and the causes that passed
their tests, each with its checks and lineage. Only metadata and aggregates
reach it, never rows. It answers with an order and a two-sentence summary. The
agent checks the answer: indices outside the list are dropped, any cause left
out keeps its deterministic place after the ones the model ordered, and a
cause can never be added. An unusable answer leaves the deterministic order.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from faultline.llm.client import LLMClient, LLMError

SYSTEM_PROMPT = """You review the diagnosis of a dbt pipeline incident.
You get the incident's symptoms and a numbered list of candidate root causes.
Every candidate already passed a deterministic test against the run's evidence.
Order the candidates from most to least likely to be the root cause, using the
symptoms, the checks and the lineage. You cannot add a cause and must not invent one.
Answer with JSON only, in this shape:
{"order": [<candidate numbers, most likely first>], "summary": "<at most two sentences>"}
"""

MAX_SYMPTOMS = 40


def prompt_sha256() -> str:
    return "sha256:" + hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()


def build_prompt(incident: dict[str, Any], causes: list[dict[str, Any]]) -> str:
    symptoms = incident.get("symptoms", [])
    lines = [f"Symptoms ({len(symptoms)}):"]
    for s in symptoms[:MAX_SYMPTOMS]:
        where = f"{s['node']}.{s['column']}" if s.get("column") else s["node"]
        lines.append(
            f"- {s['source']} at {where}: observed {s['observed']}, expected {s['expected']}"
        )
    if len(symptoms) > MAX_SYMPTOMS:
        lines.append(f"- ... and {len(symptoms) - MAX_SYMPTOMS} more")
    lines += ["", "Candidates:"]
    for i, c in enumerate(causes, start=1):
        lines.append(
            f"{i}. {c['description']} ({c['mode']}; explains {len(c['explains'])} symptoms)"
        )
        for check in c["checks"]:
            lines.append(f"   - {check['name']}: {check['detail']}")
        for path in c["lineage"][:5]:
            lines.append(f"   - lineage: {path}")
    return "\n".join(lines)


def parse_order(text: str, n: int) -> tuple[list[int], str, str | None]:
    """0-based order and summary; an error message when the answer is unusable."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return [], "", "no JSON object in the answer"
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return [], "", f"invalid JSON: {exc.msg}"
    raw = data.get("order") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return [], "", "no order list"
    order = [int(x) - 1 for x in raw if isinstance(x, int) and 1 <= x <= n]
    summary = data.get("summary") if isinstance(data.get("summary"), str) else ""
    return order, str(summary).strip(), None


class LLMReranker:
    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def __call__(
        self, incident: dict[str, Any], causes: list[dict[str, Any]]
    ) -> tuple[list[int], str, dict[str, Any]]:
        try:
            answer = self.client.complete(SYSTEM_PROMPT, build_prompt(incident, causes))
        except LLMError as exc:
            return [], "", {"error": str(exc)}
        order, summary, error = parse_order(answer, len(causes))
        info: dict[str, Any] = {"raw_answer": answer}
        if error:
            info["error"] = error
        return order, summary, info
