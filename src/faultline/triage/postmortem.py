"""A post-mortem for one incident, written only from what faultline produced.

Sections: what happened (symptoms), impact (lineage downstream of the cause),
root cause (the confirmed cause with its checks, and what else was considered),
the fix (the drafted patch, or why there is none), tests that would have caught
it (learned checks that fail on this run), and follow-ups. Nothing is added that
the triage report, lineage, fix drafter or test generator did not produce; a
missing part says so.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from faultline.collectors.dbt_artifacts import Project
from faultline.fixes.draft import Fix
from faultline.lineage.column import ProjectLineage
from faultline.lineage.impact import TargetError, impact


@dataclass(frozen=True)
class PostmortemInputs:
    run_id: str
    report: dict[str, Any]
    project: Project
    lineage: ProjectLineage
    fix: Fix | None = None
    fix_diff: str = ""
    caught_by: Sequence[str] = ()  # learned checks that fail on this run
    checked_tests: bool = False


def _where(item: dict[str, Any]) -> str:
    return f"{item['node']}.{item['column']}" if item.get("column") else item["node"]


def render(p: PostmortemInputs) -> str:
    report = p.report
    lines = [f"# Post-mortem: {p.run_id}", ""]
    if not report.get("detected"):
        return "\n".join([*lines, "No symptoms in this run. Nothing to write up."]) + "\n"
    incidents = report["incidents"]
    confirmed = [i for i in incidents if i["causes"]]
    top = confirmed[0] if confirmed else incidents[0]
    cause = top["causes"][0] if top["causes"] else None
    summary = (
        f"Root cause confirmed: {cause['description']}."
        if cause
        else "Root cause not confirmed: no proposed cause passed its test."
    )
    lines += [
        f"**Summary.** {len(report['incidents'])} incident(s) from "
        f"{sum(len(i['symptoms']) for i in incidents)} symptoms. {summary}",
        "",
        "## What happened",
        "",
    ]
    kinds = Counter(s["source"] for s in top["symptoms"])
    lines.append(
        "Symptoms by check: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())) + "."
    )
    lines += ["", "| Check | Where | Observed | Expected |", "|---|---|---|---|"]
    for s in top["symptoms"][:12]:
        lines.append(f"| {s['source']} | `{_where(s)}` | {s['observed']} | {s['expected']} |")
    if len(top["symptoms"]) > 12:
        lines.append(f"| ... | {len(top['symptoms']) - 12} more | | |")

    lines += ["", "## Impact", ""]
    if cause:
        try:
            hit = impact(p.project, p.lineage, _where(cause), "downstream")
            affected = [h.target for h in hit.hits]
            lines.append(
                f"Downstream of `{_where(cause)}`: {len(affected)} node(s)"
                + (": " + ", ".join(f"`{a}`" for a in affected[:15]) if affected else ".")
            )
            lines.append(
                f"Tests already watching that path: {len(hit.tests)}"
                + (f" ({', '.join(f'`{t}`' for t in hit.tests[:8])})." if hit.tests else ".")
            )
        except TargetError as exc:
            lines.append(f"Lineage could not place the cause: {exc}")
    else:
        lines.append("Not assessed: no confirmed cause to start from.")

    lines += ["", "## Root cause", ""]
    if cause:
        tag = "" if cause["mode"] == "observed" else " (inferred by elimination)"
        lines += [f"**{cause['description']}**{tag}", ""]
        lines += [
            f"- {'pass' if c['passed'] else 'FAIL'}: {c['name']} ({c['detail']})"
            for c in cause["checks"]
        ]
        lines.append(
            f"- explains {len(cause['explains'])} symptom(s): "
            + ", ".join(f"`{x}`" for x in cause["lineage"][:6])
        )
        others = top["causes"][1:]
        lines += [
            "",
            f"Proposed causes: {top['proposed']}; rejected by their test: {top['rejected']}."
            + (
                " Also passed: " + "; ".join(o["description"] for o in others) + "."
                if others
                else ""
            ),
        ]
    else:
        lines.append(
            f"Not confirmed. {top['proposed']} causes were proposed and all {top['rejected']} "
            "failed their tests. Look at the symptoms above by hand."
        )

    lines += ["", "## Fix", ""]
    if p.fix is None:
        lines.append("No fix drafted for this run.")
    elif p.fix.proposed:
        lines += [
            f"{p.fix.reason}. Opened only as a draft for review.",
            "",
            "```diff",
            p.fix_diff.rstrip(),
            "```",
        ]
    else:
        lines.append(f"No code fix: {p.fix.reason}.")

    lines += ["", "## Tests that would have caught it", ""]
    if not p.checked_tests:
        lines.append("Not checked for this run.")
    elif p.caught_by:
        lines.append("Checks learned from clean runs that fail on this run:")
        lines += [f"- `{c}`" for c in p.caught_by[:15]]
    else:
        lines.append("None of the learned checks fail on this run.")

    lines += ["", "## Follow-ups", ""]
    if cause and cause["kind"] == "code_change":
        lines.append(f"- Review the draft revert of commit `{(cause['commit'] or '')[:7]}`.")
    elif cause:
        lines.append(f"- Ask the owner of `{cause['node']}` to correct the data at the source.")
    if p.caught_by:
        lines.append("- Add the checks above as tests, so this fails the build next time.")
    if not cause:
        lines.append("- Triage by hand; then add a test for whatever it turns out to be.")
    return "\n".join(lines) + "\n"
