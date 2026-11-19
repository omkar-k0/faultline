"""Plain-text rendering of a triage report."""

from __future__ import annotations

from typing import Any


def render(report: dict[str, Any]) -> str:
    lines = [f"Run {report['run']}"]
    if not report["detected"]:
        return "\n".join([*lines, "No symptoms: nothing to triage."]) + "\n"
    for inc in report["incidents"]:
        lines += [
            "",
            f"Incident {inc['incident']}: {len(inc['symptoms'])} symptoms, "
            f"{inc['proposed']} causes proposed, {inc['rejected']} rejected by their test",
        ]
        if not inc["causes"]:
            lines.append("  Root cause not confirmed: no proposed cause passed its test.")
            continue
        for rank, cause in enumerate(inc["causes"], start=1):
            tag = "" if cause["mode"] == "observed" else " [inferred by elimination]"
            lines.append(f"  {rank}. {cause['description']}{tag}")
            for check in cause["checks"]:
                mark = "pass" if check["passed"] else "FAIL"
                lines.append(f"     {mark}  {check['name']}: {check['detail']}")
            paths = cause["lineage"]
            shown = ", ".join(paths[:4]) + (f" (+{len(paths) - 4} more)" if len(paths) > 4 else "")
            lines.append(f"     explains {len(cause['explains'])} symptoms: {shown}")
    return "\n".join(lines) + "\n"
