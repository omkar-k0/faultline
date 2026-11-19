"""Generate a benchmark split from a plan file.

The plan (benchmark/plan.toml) names the splits, their projects, seeds and
sizes. Nothing in this module names a particular split. Within a project,
nodes are partitioned between the splits that use it, so no seed or model is
faulted in two splits.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
import tomllib
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from faultline import __version__
from faultline.inject import faults
from faultline.inject.catalog import FaultCatalog, build_catalog
from faultline.inject.faults import FAULT_TYPES, FaultType
from faultline.inject.incident import IncidentSpec, NoCandidateError, generate
from faultline.inject.workspace import file_sha256

MANIFEST_VERSION = 1


@dataclass(frozen=True)
class SplitPlan:
    name: str
    projects: tuple[str, ...]
    seed_base: int
    incidents_per_fault: int
    clean_runs_per_project: int
    location_share: int


@dataclass(frozen=True)
class Plan:
    path: Path
    splits: dict[str, SplitPlan]

    def sha256(self) -> str:
        return file_sha256(self.path)


def load_plan(path: Path) -> Plan:
    raw = tomllib.loads(path.read_text())
    splits: dict[str, SplitPlan] = {}
    for name, cfg in raw.get("splits", {}).items():
        splits[name] = SplitPlan(
            name=name,
            projects=tuple(cfg["projects"]),
            seed_base=int(cfg["seed_base"]),
            incidents_per_fault=int(cfg["incidents_per_fault"]),
            clean_runs_per_project=int(cfg["clean_runs_per_project"]),
            location_share=int(cfg.get("location_share", 1)),
        )
    seeds = sorted(s.seed_base for s in splits.values())
    if len(seeds) != len(set(seeds)):
        raise ValueError("every split needs its own seed_base")
    return Plan(path=path, splits=splits)


def _order(project: str, node: str) -> str:
    return hashlib.sha256(f"{project}:{node}".encode()).hexdigest()


def partition(project: str, nodes: Sequence[str], shares: dict[str, int]) -> dict[str, set[str]]:
    """Assign each node to exactly one split, in proportion to the shares.

    Nodes are ordered by a hash; each goes to the split furthest below its
    share, smaller shares first on ties, so every split gets a node early.
    """
    out: dict[str, set[str]] = {name: set() for name in shares}
    for node in sorted(nodes, key=lambda n: _order(project, n)):
        name = min(shares, key=lambda n: (len(out[n]) / shares[n], shares[n], n))
        out[name].add(node)
    return out


def split_nodes(plan: Plan, catalog: FaultCatalog) -> dict[str, set[str]]:
    """Nodes of one project available to each split that uses it."""
    shares = {
        s.name: s.location_share for s in plan.splits.values() if catalog.project in s.projects
    }
    seeds = partition(catalog.project, [s.node for s in catalog.seeds], shares)
    models = partition(catalog.project, [m.node for m in catalog.models], shares)
    return {name: seeds[name] | models[name] for name in shares}


def build_specs(
    split: SplitPlan, catalogs: dict[str, FaultCatalog], allowed: dict[str, set[str]]
) -> list[tuple[IncidentSpec, frozenset[str]]]:
    """Deterministic list of incidents for a split, spread over its projects."""
    specs: list[tuple[IncidentSpec, frozenset[str]]] = []
    counter = 0

    def add(project: str, fault_type: FaultType | None) -> None:
        nonlocal counter
        counter += 1
        n = sum(1 for s, _ in specs if s.project == project) + 1
        spec = IncidentSpec(
            incident_id=f"inc_{project}_{split.name}_{n:03d}",
            project=project,
            split=split.name,
            seed=split.seed_base + counter,
            fault_type=fault_type,
        )
        specs.append((spec, frozenset(allowed[project])))

    for fault_type in FAULT_TYPES:
        able = [p for p in split.projects if faults.candidates(fault_type, catalogs[p], allowed[p])]
        if not able:
            raise NoCandidateError(f"{split.name}: no project can take {fault_type}")
        for i in range(split.incidents_per_fault):
            add(able[i % len(able)], fault_type)
    for project in split.projects:
        for _ in range(split.clean_runs_per_project):
            add(project, None)
    return specs


_CATALOGS: dict[str, FaultCatalog] = {}


def _worker(
    project_dir: str, spec: IncidentSpec, nodes: frozenset[str], run_dir: str, truth_path: str
) -> dict[str, Any]:
    if project_dir not in _CATALOGS:
        _CATALOGS[project_dir] = build_catalog(Path(project_dir))
    try:
        return generate(_CATALOGS[project_dir], spec, set(nodes), Path(run_dir), Path(truth_path))
    except NoCandidateError as exc:
        return {"incident_id": spec.incident_id, "skipped": str(exc)}


def _archive(source: Path, dest: Path) -> str:
    """A tar.gz with sorted members and zeroed metadata."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            info = tar.gettarinfo(str(path), arcname=str(path.relative_to(source.parent)))
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            with path.open("rb") as handle:
                tar.addfile(info, handle)
    with dest.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(buffer.getvalue())
    return file_sha256(dest)


def generate_split(
    plan: Plan,
    split_name: str,
    projects_dir: Path,
    benchmark_dir: Path,
    runs_dir: Path,
    dist_dir: Path,
    workers: int = 3,
    progress: Any = None,
) -> dict[str, Any]:
    split = plan.splits[split_name]
    catalogs = {
        p: build_catalog(projects_dir / p)
        for p in sorted({p for s in plan.splits.values() for p in s.projects})
    }
    allowed = {p: split_nodes(plan, catalogs[p])[split.name] for p in split.projects}
    specs = build_specs(split, catalogs, allowed)

    out_dir = benchmark_dir / split.name
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"{out_dir} is not empty; a split is generated once")
    run_root = runs_dir / split.name

    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _worker,
                str(projects_dir / spec.project),
                spec,
                nodes,
                str(run_root / spec.incident_id),
                str(out_dir / spec.incident_id / "truth.json"),
            ): spec
            for spec, nodes in specs
        }
        for done, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if progress:
                progress(done, len(futures), futures[future].incident_id)

    results.sort(key=lambda d: d["incident_id"])
    archive_name = f"benchmark-{split.name}.tar.gz"
    archive_sha = _archive(run_root, dist_dir / archive_name)
    entries = [
        {
            "id": d["incident_id"],
            "project": d["project"],
            "truth_sha256": d["hashes"]["truth"],
            "inputs": d["hashes"]["inputs"],
        }
        for d in results
        if "skipped" not in d
    ]
    section = {
        "plan_sha256": plan.sha256(),
        "archive": archive_name,
        "archive_sha256": archive_sha,
        "incidents": entries,
        "skipped": [d for d in results if "skipped" in d],
    }
    manifest_path = benchmark_dir / "manifest.json"
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text())
        if manifest_path.is_file()
        else {"schema_version": MANIFEST_VERSION, "splits": {}}
    )
    manifest["generator"] = {"faultline_version": __version__}
    manifest["splits"][split.name] = section
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return section


def summarise(benchmark_dir: Path, split_name: str) -> dict[str, Any]:
    """Counts per project and fault type, and the share of runs dbt flagged."""
    rows: dict[str, dict[str, int]] = {}
    for truth_path in sorted((benchmark_dir / split_name).glob("*/truth.json")):
        doc = json.loads(truth_path.read_text())
        fault = (doc.get("fault") or {}).get("type", "clean")
        key = f"{doc['project']}:{fault}"
        row = rows.setdefault(key, {"incidents": 0, "dbt_flagged": 0})
        row["incidents"] += 1
        obs = doc["observed"]
        row["dbt_flagged"] += int(
            obs["dbt_status"] != "success" or bool(obs["failed_tests"]) or bool(obs["warned_tests"])
        )
    return rows
