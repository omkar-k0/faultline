"""Generate one incident: copy, resample, inject, run, write ground truth.

Ground truth (truth.json, schema_version 1) records what was injected and
where, and what the run actually showed. It never predicts symptoms.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from faultline.inject import faults
from faultline.inject.catalog import FaultCatalog
from faultline.inject.faults import Applied, Candidate, FaultType
from faultline.inject.resample import resample
from faultline.inject.run import RunCapture, observed, profile_diff, run_dbt, save_run
from faultline.inject.workspace import create, file_sha256, git_init, tree_hash

SCHEMA_VERSION = 1
MAX_ATTEMPTS = 6


class NoCandidateError(RuntimeError):
    """No location in the allowed nodes can take this fault type."""


@dataclass(frozen=True)
class IncidentSpec:
    incident_id: str
    project: str
    split: str
    seed: int
    fault_type: FaultType | None  # None for a clean run


def _rng(spec: IncidentSpec, stream: str) -> random.Random:
    return random.Random(f"{spec.project}:{spec.seed}:{stream}")


def prepare(catalog: FaultCatalog, dest: Path, spec: IncidentSpec) -> tuple[Path, str]:
    """A resampled clean workspace with one commit. Same spec, same files."""
    ws = create(catalog.project_dir, dest)
    (ws / ".gitignore").write_text("target/\nlogs/\ndbt_packages/\n")
    resample(ws, catalog, _rng(spec, "resample"))
    return ws, git_init(ws)


def _reset(ws: Path, commit: str) -> None:
    subprocess.run(["git", "-C", str(ws), "reset", "-q", "--hard", commit], check=True)
    subprocess.run(["git", "-C", str(ws), "clean", "-q", "-fd"], check=True)


def ordered_candidates(
    catalog: FaultCatalog, spec: IncidentSpec, nodes: set[str]
) -> list[Candidate]:
    if spec.fault_type is None:
        return []
    cands = faults.candidates(spec.fault_type, catalog, nodes)
    if not cands:
        raise NoCandidateError(
            f"{spec.fault_type} has no candidate in {catalog.project} for this split"
        )
    _rng(spec, "choose").shuffle(cands)
    return cands


def inject_only(
    catalog: FaultCatalog, dest: Path, spec: IncidentSpec, nodes: set[str]
) -> tuple[Path, str, Applied | None]:
    """Prepare and inject the first candidate, without running dbt (used by tests)."""
    ws, clean = prepare(catalog, dest, spec)
    cands = ordered_candidates(catalog, spec, nodes)
    if not cands:
        return ws, clean, None
    return ws, clean, faults.apply(ws, catalog, cands[0], _rng(spec, "fault"))


def truth_document(
    spec: IncidentSpec, applied: Applied | None, obs: dict[str, Any], inputs: str, attempts: int
) -> dict[str, Any]:
    fault: dict[str, Any] | None = None
    location: dict[str, Any] | None = None
    if applied is not None and applied.location is not None:
        fault = {"type": applied.fault_type, "class": applied.fault_class, "params": applied.params}
        loc = asdict(applied.location)
        location = {k: loc[k] for k in ("node", "column", "commit")}
        location["physical"] = loc["physical"]
        location["file"] = loc["file"]
    return {
        "schema_version": SCHEMA_VERSION,
        "incident_id": spec.incident_id,
        "project": spec.project,
        "split": spec.split,
        "seed": spec.seed,
        "fault": fault,
        "location": location,
        "observed": obs,
        "generation": {"attempts": attempts},
        "hashes": {"inputs": inputs},
    }


def generate(
    catalog: FaultCatalog,
    spec: IncidentSpec,
    nodes: set[str],
    run_dir: Path,
    truth_path: Path,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """Generate one incident. Code faults that change nothing are skipped (equivalent mutants)."""
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        ws, clean_commit = prepare(catalog, Path(tmp) / "ws", spec)
        cands = ordered_candidates(catalog, spec, nodes)
        clean_profile: dict[str, Any] | None = None
        applied: Applied | None = None
        capture: RunCapture | None = None
        attempts = 0
        for cand in cands[:MAX_ATTEMPTS] if cands else [None]:
            attempts += 1
            if cand is not None:
                _reset(ws, clean_commit)
                applied = faults.apply(ws, catalog, cand, _rng(spec, f"fault:{attempts}"))
            capture = run_dbt(ws)
            if cand is None or applied is None or applied.fault_class == "data":
                break
            if clean_profile is None:
                ref, _ = prepare(catalog, Path(tmp) / "clean_ref", spec)
                clean_profile = run_dbt(ref).profile
                shutil.rmtree(ref)
            if not capture.build_ok or profile_diff(clean_profile, capture.profile):
                break
            applied, capture = None, None  # equivalent mutant: try the next site
        if spec.fault_type is not None and applied is None:
            raise NoCandidateError(f"no observable {spec.fault_type} in {attempts} attempts")
        assert capture is not None
        obs = observed(capture)
        if applied is not None and applied.fault_class == "code" and clean_profile is not None:
            obs["changed_relations"] = profile_diff(clean_profile, capture.profile)
        inputs = tree_hash(ws)
        save_run(ws, capture, run_dir)
    doc = truth_document(spec, applied, obs, inputs, attempts)
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    doc["hashes"]["truth"] = file_sha256(truth_path)
    return doc
