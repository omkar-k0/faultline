"""Run dbt in a workspace and capture what happened.

Captured: dbt's artefacts and log, the workspace git log, and an aggregate
profile of every relation (row count, null and distinct counts, numeric
min/max/mean/median, date ranges). No raw rows are stored.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from faultline.inject.workspace import git_log

ARTEFACTS = ("run_results.json", "manifest.json", "catalog.json")
NUMERIC_TYPES = ("INT", "DECIMAL", "DOUBLE", "FLOAT", "REAL", "NUMERIC", "HUGEINT", "BIGINT")
TIME_TYPES = ("DATE", "TIMESTAMP", "TIME")


@dataclass
class RunCapture:
    steps: dict[str, int] = field(default_factory=dict)  # step -> exit code
    run_results: dict[str, Any] | None = None
    profile: dict[str, Any] = field(default_factory=dict)

    @property
    def build_ok(self) -> bool:
        return self.steps.get("build", 1) == 0


def run_dbt(ws: Path, timeout: int = 900) -> RunCapture:
    """deps, seed, build, docs generate, in one subprocess (see dbt_session)."""
    env = {
        **os.environ,
        "FAULTLINE_DUCKDB_DIR": str(ws / "target"),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DBT_USE_COLORS": "false",
    }
    (ws / "target").mkdir(exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "faultline.inject.dbt_session", str(ws)],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
    capture = RunCapture()
    steps_file = ws / "target" / "steps.json"
    capture.steps = json.loads(steps_file.read_text()) if steps_file.is_file() else {"build": 2}
    results = ws / "target" / "build_run_results.json"
    capture.run_results = json.loads(results.read_text()) if results.is_file() else None
    capture.profile = profile_workspace(ws)
    return capture


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _clean(value: Any) -> Any:
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else round(value, 6)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, int | str) or value is None:
        return value
    return str(value)


def profile_relation(con: duckdb.DuckDBPyConnection, relation: str) -> dict[str, Any]:
    try:
        described = con.sql(f"describe {relation}").fetchall()
    except duckdb.Error:
        return {"missing": True}
    columns = [(str(r[0]), str(r[1]).upper()) for r in described]
    parts = ["count(*)"]
    plan: list[tuple[str, str, list[str]]] = []
    for name, ctype in columns:
        col = _q(name)
        stats = ["non_null", "distinct"]
        parts += [f"count({col})", f"approx_count_distinct({col})"]
        if ctype.startswith(NUMERIC_TYPES):
            stats += ["min", "max", "mean", "median"]
            parts += [
                f"min({col})::double",
                f"max({col})::double",
                f"avg({col})::double",
                f"quantile_cont({col}, 0.5)::double",
            ]
        elif ctype.startswith(TIME_TYPES):
            stats += ["min", "max"]
            parts += [f"min({col})", f"max({col})"]
        plan.append((name, ctype, stats))
    try:
        row = con.sql(f"select {', '.join(parts)} from {relation}").fetchall()[0]
    except duckdb.Error as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    out: dict[str, Any] = {"rows": row[0], "columns": {}}
    i = 1
    for name, ctype, stats in plan:
        values = {s: _clean(row[i + k]) for k, s in enumerate(stats)}
        values["type"] = ctype
        out["columns"][name] = values
        i += len(stats)
    return out


def profile_workspace(ws: Path) -> dict[str, Any]:
    manifest_path = ws / "target" / "manifest.json"
    dbs = sorted((ws / "target").glob("*.duckdb"))
    if not manifest_path.is_file() or not dbs:
        return {}
    manifest = json.loads(manifest_path.read_text())
    nodes = list(manifest.get("nodes", {}).values()) + list(manifest.get("sources", {}).values())
    con = duckdb.connect(str(dbs[0]), read_only=True)
    try:
        profile: dict[str, Any] = {}
        for node in sorted(nodes, key=lambda n: n["unique_id"]):
            if node["resource_type"] not in {"model", "seed", "source", "snapshot"}:
                continue
            if (node.get("config") or {}).get("materialized") == "ephemeral":
                continue
            relation = node.get("relation_name")
            if relation:
                profile[node["unique_id"]] = profile_relation(con, relation)
        return profile
    finally:
        con.close()


def profile_diff(a: dict[str, Any], b: dict[str, Any], tol: float = 1e-9) -> list[str]:
    """Node ids whose profile differs between two runs."""
    changed = []
    for node in sorted(set(a) | set(b)):
        if not _same(a.get(node), b.get(node), tol):
            changed.append(node)
    return changed


def _same(x: Any, y: Any, tol: float) -> bool:
    if isinstance(x, dict) and isinstance(y, dict):
        return x.keys() == y.keys() and all(_same(x[k], y[k], tol) for k in x)
    if isinstance(x, float) and isinstance(y, float):
        return abs(x - y) <= tol * max(1.0, abs(x), abs(y))
    return bool(x == y)


def observed(capture: RunCapture) -> dict[str, Any]:
    results = (capture.run_results or {}).get("results", [])
    failed_tests = sorted(
        r["unique_id"]
        for r in results
        if r["unique_id"].startswith("test.") and r["status"] in {"fail", "error"}
    )
    warned_tests = sorted(
        r["unique_id"]
        for r in results
        if r["unique_id"].startswith("test.") and r["status"] == "warn"
    )
    error_nodes = sorted(
        r["unique_id"]
        for r in results
        if not r["unique_id"].startswith("test.") and r["status"] == "error"
    )
    skipped = sorted(r["unique_id"] for r in results if r["status"] == "skipped")
    return {
        "dbt_status": "success" if capture.build_ok else "error",
        "steps": capture.steps,
        "failed_tests": failed_tests,
        "warned_tests": warned_tests,
        "error_nodes": error_nodes,
        "skipped_nodes": len(skipped),
    }


def save_run(ws: Path, capture: RunCapture, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    target = ws / "target"
    for name in ARTEFACTS:
        src = target / ("build_run_results.json" if name == "run_results.json" else name)
        if src.is_file():
            shutil.copy(src, out / name)
    log = ws / "logs" / "dbt.log"
    if log.is_file():
        shutil.copy(log, out / "dbt.log")
    (out / "profile.json").write_text(json.dumps(capture.profile, indent=1, sort_keys=True))
    (out / "git.log").write_text(git_log(ws) + "\n")
