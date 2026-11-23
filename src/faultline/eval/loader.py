"""Load benchmark incidents for evaluation.

A method under test sees only what an engineer would have after a run: dbt's
artefacts and log, an aggregate profile of every table, and a cleaned git
history. Ground truth is read separately, by the scorer only (`truth.py`).

The saved git log was written by the injector, so it carries its commit
messages and commits for seed-data changes, which real history never has.
`clean_history` keeps only commits that touch model SQL and replaces every
message with "commit N". The rule never looks at ground truth.
"""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
import urllib.request
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from faultline.eval.splits import FINAL_SPLIT

RELEASE_URL = "https://github.com/omkar-k0/faultline/releases/download/benchmark-v1/{name}"
# Splits this milestone may evaluate. The frozen split is scored once, at the end.
EVALUABLE_SPLITS = frozenset({"train", "dev"})  # the final split: see eval/splits.py
_COMMIT_LINE = re.compile(r"^([0-9a-f]{40}) (.*)$")
_MODEL_SQL = re.compile(r"(^|/)models/.+\.sql$")


class BenchmarkError(RuntimeError):
    """A split, archive or incident is missing, tampered with or not allowed."""


@dataclass(frozen=True)
class Commit:
    hash: str
    message: str
    files: tuple[str, ...]


def parse_git_log(text: str) -> list[tuple[str, str, tuple[str, ...]]]:
    """Parse `git log --format='%H %s' --name-status` output, newest first."""
    commits: list[tuple[str, str, list[str]]] = []
    for line in text.splitlines():
        match = _COMMIT_LINE.match(line)
        if match:
            commits.append((match.group(1), match.group(2), []))
        elif line.strip() and commits:
            parts = line.split("\t")
            if len(parts) >= 2:
                commits[-1][2].append(parts[-1])
    return [(h, s, tuple(f)) for h, s, f in commits]


def clean_history(text: str) -> tuple[Commit, ...]:
    """Commits that touch model SQL, oldest first, messages replaced by 'commit N'."""
    kept = [
        (h, files)
        for h, _subject, files in reversed(parse_git_log(text))
        if any(_MODEL_SQL.search(f) for f in files)
    ]
    return tuple(
        Commit(hash=h, message=f"commit {i}", files=files)
        for i, (h, files) in enumerate(kept, start=1)
    )


@dataclass(frozen=True)
class Incident:
    """One benchmark run, as a method under test may see it. No ground truth."""

    incident_id: str
    project: str
    run_dir: Path

    def _json(self, name: str) -> dict[str, Any] | None:
        path = self.run_dir / name
        if not path.is_file():
            return None
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None

    @cached_property
    def run_results(self) -> dict[str, Any] | None:
        return self._json("run_results.json")

    @cached_property
    def manifest(self) -> dict[str, Any] | None:
        return self._json("manifest.json")

    @cached_property
    def profile(self) -> dict[str, Any]:
        return self._json("profile.json") or {}

    @cached_property
    def dbt_log(self) -> str:
        path = self.run_dir / "dbt.log"
        return path.read_text(errors="replace") if path.is_file() else ""

    @cached_property
    def history(self) -> tuple[Commit, ...]:
        path = self.run_dir / "git.log"
        return clean_history(path.read_text()) if path.is_file() else ()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def split_section(benchmark_dir: Path, split: str, allow_final: bool = False) -> dict[str, Any]:
    allowed = EVALUABLE_SPLITS | ({FINAL_SPLIT} if allow_final else set())
    if split not in allowed:
        raise BenchmarkError(f"split {split!r} cannot be evaluated in this milestone")
    manifest = json.loads((benchmark_dir / "manifest.json").read_text())
    try:
        section: dict[str, Any] = manifest["splits"][split]
    except KeyError as exc:
        raise BenchmarkError(f"benchmark/manifest.json has no split {split!r}") from exc
    return section


def ensure_archive(section: dict[str, Any], dist_dir: Path, download: bool = True) -> Path:
    """The split's archive in dist/, downloaded from the release if missing, hash-checked."""
    path: Path = dist_dir / str(section["archive"])
    expected = str(section["archive_sha256"])
    if not path.is_file():
        if not download:
            raise BenchmarkError(f"{path} missing; run `make fetch-benchmark` or allow download")
        dist_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        urllib.request.urlretrieve(RELEASE_URL.format(name=section["archive"]), tmp)
        tmp.replace(path)
    actual = _sha256(path)
    if actual != expected:
        raise BenchmarkError(f"{path} has sha256 {actual}, manifest says {expected}")
    return path


def extract(archive: Path, runs_dir: Path, archive_sha: str) -> None:
    """Unpack once per archive hash. Refuses members outside the target folder."""
    marker = runs_dir / f".extracted-{archive_sha.removeprefix('sha256:')[:16]}"
    if marker.is_file():
        return
    runs_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            target = (runs_dir / member.name).resolve()
            if not target.is_relative_to(runs_dir.resolve()) or not (
                member.isfile() or member.isdir()
            ):
                raise BenchmarkError(f"unsafe archive member {member.name!r}")
        tar.extractall(runs_dir, filter="data")
    marker.write_text(archive_sha + "\n")


def load_incidents(
    split: str,
    benchmark_dir: Path = Path("benchmark"),
    dist_dir: Path = Path("dist"),
    runs_dir: Path = Path("build/eval"),
    download: bool = True,
    allow_final: bool = False,
) -> tuple[list[Incident], dict[str, Any]]:
    """Incidents of a split in manifest order, plus the manifest section.
    `allow_final` is set by `run_eval` only (see eval/splits.py)."""
    section = split_section(benchmark_dir, split, allow_final)
    archive = ensure_archive(section, dist_dir, download)
    extract(archive, runs_dir, section["archive_sha256"])
    incidents = []
    for entry in sorted(section["incidents"], key=lambda e: e["id"]):
        run_dir = runs_dir / split / entry["id"]
        if not run_dir.is_dir():
            raise BenchmarkError(f"{run_dir} missing from {archive.name}")
        if (run_dir / "truth.json").exists():
            raise BenchmarkError(f"{run_dir} contains ground truth; methods must not see it")
        incidents.append(Incident(entry["id"], entry["project"], run_dir))
    return incidents, section
