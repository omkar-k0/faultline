"""Turn a drafted fix into a branch and a draft pull request, then stop.

CLAUDE.md principle 4: humans approve changes. Nothing here merges, deploys or
writes to a warehouse; the only remote action is `gh pr create --draft`. Without
`open_pr`, the fix is written as a patch file and a PR description only.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from faultline.fixes.draft import Fix

Runner = Callable[[Sequence[str], Path], str]


def run(cmd: Sequence[str], cwd: Path) -> str:
    return subprocess.run(list(cmd), cwd=cwd, capture_output=True, text=True, check=True).stdout


def pr_body(run_id: str, fix: Fix, report_lines: Sequence[str] = ()) -> str:
    lines = [
        f"Drafted by faultline for incident `{run_id}`. "
        "Review before merging; faultline never merges.",
        "",
        f"**Cause:** {fix.cause}",
        f"**Fix:** {fix.reason}",
        "",
        "**Files:**",
        *[f"- `{p}`" for p in sorted(fix.files)],
    ]
    if report_lines:
        lines += ["", "**Evidence:**", *report_lines]
    return "\n".join(lines) + "\n"


def write_draft(repo: Path, run_id: str, fix: Fix, out_dir: Path) -> list[Path]:
    """The patch and the PR text, as files. Changes nothing in the repo."""
    out_dir.mkdir(parents=True, exist_ok=True)
    patch = out_dir / f"{run_id}.patch"
    body = out_dir / f"{run_id}.md"
    patch.write_text(fix.diff(repo))
    body.write_text(pr_body(run_id, fix))
    return [patch, body]


def open_draft_pr(repo: Path, run_id: str, fix: Fix, runner: Runner = run) -> str:
    """Branch, commit, push, and open a draft PR. Returns the PR URL. Never merges."""
    if not fix.proposed:
        raise ValueError(f"no fix to open: {fix.reason}")
    branch = f"faultline/fix-{run_id}"
    runner(["git", "switch", "-c", branch], repo)
    for path, content in fix.files.items():
        (repo / path).write_text(content)
    runner(["git", "add", *sorted(fix.files)], repo)
    runner(["git", "commit", "-m", f"fix: {fix.reason}"], repo)
    runner(["git", "push", "-u", "origin", branch], repo)
    url = runner(
        [
            "gh",
            "pr",
            "create",
            "--draft",
            "--title",
            f"faultline: {fix.cause}"[:120],
            "--body",
            pr_body(run_id, fix),
            "--head",
            branch,
        ],
        repo,
    )
    return url.strip()
