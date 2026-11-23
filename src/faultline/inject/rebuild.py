"""Rebuild a benchmark run's workspace exactly, for fixes and generated tests (M7).

The archives hold each run's profile and dbt artefacts, not its files or
database. To try a fix, or run generated tests, the run's workspace is rebuilt
from its ground-truth record: same project, seed and fault site, so the same
resampled data and the same fault. The rebuilt files are checked against the
input hash recorded when the run was generated; a mismatch stops everything.

This is harness code: it reads ground truth to rebuild the scene, the way the
generator built it. Methods under test (the fix drafter, the test generator)
never see the truth. Only train and dev runs are ever rebuilt.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from faultline.inject import faults
from faultline.inject.benchmark import load_plan, split_nodes
from faultline.inject.catalog import FaultCatalog, build_catalog
from faultline.inject.incident import IncidentSpec, _reset, _rng, ordered_candidates, prepare
from faultline.inject.workspace import tree_hash

REBUILDABLE_SPLITS = frozenset({"train", "dev"})


class RebuildMismatch(RuntimeError):
    """The rebuilt files differ from the ones the run was generated from."""


@dataclass(frozen=True)
class Rebuilt:
    workspace: Path
    clean_commit: str  # the workspace before the fault
    fault_commit: str | None  # HEAD after a code fault, None otherwise


@cache
def _catalog(project_dir: str) -> FaultCatalog:
    return build_catalog(Path(project_dir))


def spec_from_truth(truth: dict[str, Any]) -> IncidentSpec:
    fault = truth.get("fault")
    return IncidentSpec(
        incident_id=truth["incident_id"],
        project=truth["project"],
        split=truth["split"],
        seed=int(truth["seed"]),
        fault_type=fault["type"] if fault else None,
    )


def load_truth_doc(benchmark_dir: Path, split: str, incident_id: str) -> dict[str, Any]:
    if split not in REBUILDABLE_SPLITS:
        raise ValueError(f"runs of {split!r} are never rebuilt")
    doc: dict[str, Any] = json.loads(
        (benchmark_dir / split / incident_id / "truth.json").read_text()
    )
    return doc


def rebuild(
    truth: dict[str, Any],
    dest: Path,
    projects_dir: Path = Path("projects"),
    plan_path: Path = Path("benchmark/plan.toml"),
    clean: bool = False,
) -> Rebuilt:
    """The run's workspace at `dest`; with `clean=True`, the same run without its fault."""
    spec = spec_from_truth(truth)
    if spec.split not in REBUILDABLE_SPLITS:
        raise ValueError(f"runs of {spec.split!r} are never rebuilt")
    catalog = _catalog(str(projects_dir / spec.project))
    ws, clean_commit = prepare(catalog, dest, spec)
    if clean or spec.fault_type is None:
        if spec.fault_type is None and tree_hash(ws) != truth["hashes"]["inputs"]:
            raise RebuildMismatch(f"{spec.incident_id}: rebuilt clean files differ")
        return Rebuilt(ws, clean_commit, None)
    nodes = split_nodes(load_plan(plan_path), catalog)[spec.split]
    attempts = int(truth["generation"]["attempts"])
    cands = ordered_candidates(catalog, spec, nodes)
    _reset(ws, clean_commit)
    applied = faults.apply(ws, catalog, cands[attempts - 1], _rng(spec, f"fault:{attempts}"))
    if tree_hash(ws) != truth["hashes"]["inputs"]:
        raise RebuildMismatch(f"{spec.incident_id}: rebuilt files differ from the recorded run")
    head = None
    if applied.fault_class == "code":
        head = subprocess.run(
            ["git", "-C", str(ws), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    return Rebuilt(ws, clean_commit, head)
