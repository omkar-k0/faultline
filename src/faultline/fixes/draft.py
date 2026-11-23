"""Draft a fix for a confirmed cause. A draft is files to change, never applied by itself.

One pattern per kind of cause; anything else gets no code fix, with the reason:

- code change in a model: put that model's file back as it was before the commit.
- duplicate rows on a source key: the models that read the source keep one copy of
  each identical row (`select distinct`). The duplicates in the benchmark are exact
  copies; a fix test shows whether that holds for a given run.
- a source column renamed (old column missing, a new one appeared): the models that
  read the source see the new column under the old name. Only for seeds, whose
  reference can be rewritten in place; sources read through package macros get none.
- anything else (null spikes, distribution shifts, late or missing rows, time
  shifts, dropped or retyped columns): no code fix. Changing a model to hide bad
  input would mask the incident; the fix belongs at the source, and the draft says so.

Humans approve every change (CLAUDE.md principle 4): this module only proposes.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from faultline.collectors.dbt_artifacts import Project
from faultline.triage.hypotheses import file_matches

FIX_HEADER = "-- faultline fix: {why}\n"


@dataclass(frozen=True)
class Fix:
    pattern: str  # revert_commit | dedupe_rows | map_renamed_column | none
    cause: str
    reason: str
    files: dict[str, str] = field(default_factory=dict)  # path in the repo -> new content

    @property
    def proposed(self) -> bool:
        return bool(self.files)

    def diff(self, repo: Path) -> str:
        out: list[str] = []
        for path in sorted(self.files):
            old = (repo / path).read_text() if (repo / path).exists() else ""
            out += difflib.unified_diff(
                old.splitlines(keepends=True),
                self.files[path].splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        return "".join(out)


def no_fix(cause: dict[str, Any], reason: str) -> Fix:
    return Fix("none", cause.get("description", ""), reason)


def model_path(repo: Path, project: Project, node_id: str) -> str | None:
    """The model's file in the repo: its own path, or the same path in a package folder."""
    node = project.nodes.get(node_id)
    if node is None or not node.original_file_path:
        return None
    ofp = node.original_file_path
    if (repo / ofp).is_file() and node.package == root_package(repo):
        return ofp
    hits = sorted(
        str(p.relative_to(repo))
        for p in repo.rglob(Path(ofp).name)
        if str(p.relative_to(repo)).endswith(ofp) and "target" not in p.parts
    )
    return hits[0] if hits else None


def root_package(repo: Path) -> str | None:
    """The `name:` in the repo's dbt_project.yml."""
    path = repo / "dbt_project.yml"
    if not path.is_file():
        return None
    match = re.search(r"^name:\s*['\"]?([\w-]+)", path.read_text(), re.MULTILINE)
    return match.group(1) if match else None


def children(project: Project, node_id: str) -> list[str]:
    return sorted(
        uid
        for uid, n in project.nodes.items()
        if n.resource_type == "model" and node_id in n.depends_on
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def revert_commit(repo: Path, project: Project, cause: dict[str, Any]) -> Fix:
    commit = cause["commit"]
    node = project.nodes.get(cause["node"])
    changed = _git(repo, "show", "--name-only", "--format=", commit).split()
    paths = [p for p in changed if node is not None and file_matches(node.original_file_path, p)]
    if not paths:
        return no_fix(cause, f"commit {commit[:7]} does not touch the model's file")
    files = {p: _git(repo, "show", f"{commit}^:{p}") for p in paths}
    why = f"revert the change commit {commit[:7]} made to this model"
    return Fix("revert_commit", cause["description"], why, files)


def dedupe_rows(repo: Path, project: Project, cause: dict[str, Any]) -> Fix:
    readers = children(project, cause["node"])
    files: dict[str, str] = {}
    for uid in readers:
        path = model_path(repo, project, uid)
        if path is None:
            continue
        sql = (repo / path).read_text().rstrip().rstrip(";")
        why = f"{cause['node']} repeats rows on key {cause['column']}; keep one copy of each"
        files[path] = (
            FIX_HEADER.format(why=why)
            + "with faultline_input as (\n\n"
            + sql
            + "\n\n)\nselect distinct * from faultline_input\n"
        )
    if not files:
        return no_fix(cause, "no model file reads this source directly")
    reason = (
        f"keep one copy of each identical row in the {len(files)} model(s) reading "
        f"{cause['node']}; the source itself should stop sending duplicates"
    )
    return Fix("dedupe_rows", cause["description"], reason, files)


def _renamed_to(incident: dict[str, Any], node: str) -> list[str]:
    return sorted(
        s["column"]
        for s in incident.get("symptoms", [])
        if s["source"] == "schema" and s["node"] == node and s["observed"] == "new" and s["column"]
    )


def map_renamed_column(
    repo: Path, project: Project, cause: dict[str, Any], incident: dict[str, Any]
) -> Fix:
    old, node_id = cause["column"], cause["node"]
    new = _renamed_to(incident, node_id)
    if len(new) != 1:
        return no_fix(cause, "the column is missing and no single new column replaced it")
    node = project.nodes.get(node_id)
    if node is None or node.resource_type != "seed":
        return no_fix(cause, "the source is read through package macros; rename it at the source")
    ref = re.compile(r"\{\{\s*ref\(\s*['\"]" + re.escape(node.name) + r"['\"]\s*\)\s*\}\}")
    files: dict[str, str] = {}
    replacement = f'(select *, "{new[0]}" as "{old}" from {{{{ ref(\'{node.name}\') }}}})'
    for uid in children(project, node_id):
        path = model_path(repo, project, uid)
        if path is None:
            continue
        sql = (repo / path).read_text()
        patched, count = ref.subn(lambda _m: replacement, sql)
        if count:
            why = f"{node.name}.{old} was renamed to {new[0]}; read it under the old name"
            files[path] = FIX_HEADER.format(why=why) + patched
    if not files:
        return no_fix(cause, "no model file references the seed directly")
    reason = f"map {new[0]} back to {old} where the seed is read, until the source is fixed"
    return Fix("map_renamed_column", cause["description"], reason, files)


def draft(repo: Path, project: Project, cause: dict[str, Any], incident: dict[str, Any]) -> Fix:
    """The fix for one confirmed cause, as it appears in a triage report."""
    kind = cause["kind"]
    if kind == "code_change" and cause.get("commit"):
        return revert_commit(repo, project, cause)
    if kind == "duplicate_rows":
        return dedupe_rows(repo, project, cause)
    if kind == "source_column" and any(
        s["source"] == "schema" and s["observed"] == "missing"
        for s in cause.get("explains", [])
        if s["node"] == cause["node"]
    ):
        fix = map_renamed_column(repo, project, cause, incident)
        if fix.proposed or "macros" in fix.reason or "single new column" not in fix.reason:
            return fix
        return no_fix(cause, "the column was dropped at the source; restore it there")
    return no_fix(
        cause,
        "the data changed at the source; a model change would hide it, so the fix is at the "
        "source, and a test can catch it next time",
    )
