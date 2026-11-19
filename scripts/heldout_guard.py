"""CI guard for the frozen heldout split.

Fails a pull request when it:
1. adds, changes, deletes or renames any file under benchmark/heldout/, or
2. adds a line under src/ that mentions "heldout", outside the allowlisted
   files that implement `faultline eval --split heldout`.

One exception, the freeze: when HELDOUT_FREEZE=true (the PR carries the
owner's `heldout-freeze` label) and benchmark/heldout/ is empty on the base,
the PR may add files under benchmark/heldout/ and modify the files in
FREEZE_ALSO_ALLOWED, and nothing else. After that, heldout is frozen.

Usage: python scripts/heldout_guard.py <base-ref>
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass

HELDOUT_DIR = "benchmark/heldout/"
SRC_DIR = "src/"
HELDOUT_PATTERN = re.compile(r"held[\s_\-/]*out", re.IGNORECASE)

# Files allowed to name the heldout split. Only the scoring entry point of
# `faultline eval --split heldout` belongs here. Changes to this list are
# owner-reviewed through CODEOWNERS.
ALLOWED_SRC_FILES: frozenset[str] = frozenset({"src/faultline/eval/splits.py"})

# Besides adding heldout files, a freeze PR may change only these.
FREEZE_ALSO_ALLOWED: frozenset[str] = frozenset({"benchmark/manifest.json", "benchmark/plan.toml"})


@dataclass(frozen=True)
class FileChange:
    status: str
    path: str
    old_path: str | None = None


@dataclass(frozen=True)
class AddedLine:
    path: str
    number: int
    text: str


def parse_name_status(output: str) -> list[FileChange]:
    """Parse `git diff --name-status -M` output."""
    changes: list[FileChange] = []
    for raw in output.splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t")
        status = parts[0]
        if status[:1] in {"R", "C"} and len(parts) == 3:
            changes.append(FileChange(status=status[:1], path=parts[2], old_path=parts[1]))
        elif len(parts) == 2:
            changes.append(FileChange(status=status[:1], path=parts[1]))
    return changes


def parse_added_lines(diff: str) -> list[AddedLine]:
    """Collect added lines from a unified diff produced with -U0."""
    added: list[AddedLine] = []
    path: str | None = None
    number = 0
    hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            path = target[2:] if target.startswith("b/") else None
            continue
        match = hunk.match(raw)
        if match:
            number = int(match.group(1))
            continue
        if path is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            added.append(AddedLine(path=path, number=number, text=raw[1:]))
            number += 1
    return added


def find_freeze_violations(changes: list[FileChange], base_has_heldout: bool) -> list[str]:
    if base_has_heldout:
        return [
            "benchmark/heldout/ is already frozen on the base branch; it cannot be frozen again"
        ]
    violations: list[str] = []
    added = 0
    for change in changes:
        paths = [change.path] + ([change.old_path] if change.old_path else [])
        if change.status == "A" and change.path.startswith(HELDOUT_DIR):
            added += 1
            continue
        if change.status == "M" and change.path in FREEZE_ALSO_ALLOWED:
            continue
        if change.status == "A" and change.path in FREEZE_ALSO_ALLOWED:
            continue
        for path in paths:
            violations.append(
                f"{change.status} {path}: a freeze PR may only add benchmark/heldout/ files"
            )
    if added == 0:
        violations.append("freeze PR adds no files under benchmark/heldout/")
    return violations


def find_violations(changes: list[FileChange], added: list[AddedLine]) -> list[str]:
    violations: list[str] = []
    for change in changes:
        touched = [change.path] + ([change.old_path] if change.old_path else [])
        for path in touched:
            if path.startswith(HELDOUT_DIR):
                violations.append(f"{change.status} {path}: benchmark/heldout/ is frozen")
    for line in added:
        if not line.path.startswith(SRC_DIR) or line.path in ALLOWED_SRC_FILES:
            continue
        if HELDOUT_PATTERN.search(line.text):
            violations.append(
                f"{line.path}:{line.number}: src/ code may not reference the heldout split"
            )
    return violations


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: heldout_guard.py <base-ref>", file=sys.stderr)
        return 2
    base = argv[1]
    changes = parse_name_status(_git("diff", "--name-status", "-M", f"{base}...HEAD"))
    if os.environ.get("HELDOUT_FREEZE", "").lower() == "true":
        base_has_heldout = bool(
            _git("ls-tree", "-r", "--name-only", base, "--", HELDOUT_DIR).strip()
        )
        violations = find_freeze_violations(changes, base_has_heldout)
        for violation in violations:
            print(f"heldout-guard (freeze): {violation}")
        if violations:
            return 1
        print(f"heldout-guard (freeze): ok, {len(changes)} files")
        return 0
    added = parse_added_lines(_git("diff", "-U0", "--no-color", f"{base}...HEAD", "--", SRC_DIR))
    violations = find_violations(changes, added)
    for violation in violations:
        print(f"heldout-guard: {violation}")
    if violations:
        return 1
    print(f"heldout-guard: ok ({len(changes)} files checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
