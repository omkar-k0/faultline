"""A throwaway copy of a test project, with its own git history.

The vendored project under `projects/` is never modified. Commits use a fixed
author and date, so the same inputs give the same commit hashes.
"""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

IGNORED = frozenset({"target", "logs", "dbt_packages", ".git", "__pycache__"})
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "faultline-injector",
    "GIT_AUTHOR_EMAIL": "injector@faultline.invalid",
    "GIT_COMMITTER_NAME": "faultline-injector",
    "GIT_COMMITTER_EMAIL": "injector@faultline.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}

Rows = list[list[str]]


def create(project_dir: Path, dest: Path) -> Path:
    """Copy a project into `dest` (which must not exist), skipping build output."""
    if dest.exists():
        raise FileExistsError(dest)
    shutil.copytree(project_dir, dest, ignore=lambda _d, names: [n for n in names if n in IGNORED])
    return dest


def _git(root: Path, *args: str) -> str:
    env = {
        **os.environ,
        **_GIT_ENV,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
    result = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True, env=env
    )
    return result.stdout.strip()


def git_init(root: Path, message: str = "clean project") -> str:
    _git(root, "init", "-q", "-b", "main")
    return git_commit(root, message)


def git_commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def git_log(root: Path) -> str:
    return _git(root, "log", "--format=%H %s", "--name-status")


def git_changed_files(root: Path, base: str, head: str = "HEAD") -> list[str]:
    out = _git(root, "diff", "--name-only", base, head)
    return [line for line in out.splitlines() if line]


def read_csv(path: Path) -> tuple[list[str], Rows]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        return header, [row for row in reader]


def write_csv(path: Path, header: list[str], rows: Rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_file() and not (set(rel.parts) & IGNORED):
            yield path


def tree_hash(root: Path) -> str:
    """sha256 over every input file (path and content), ignoring build output."""
    digest = hashlib.sha256()
    for path in _files(root):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return "sha256:" + digest.hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
