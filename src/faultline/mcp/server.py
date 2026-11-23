"""faultline as an MCP server: read-only tools for an assistant such as Claude.

`faultline mcp` serves over stdio. Every tool only reads: the incident store,
a dbt project's built artefacts, and the eval result files. None writes, runs
dbt, or touches a warehouse; each is marked read-only to the client.

Configured in faultline.toml under [mcp]: the dbt project to read lineage from
and the incident store. Names given to `get_results` are checked against the
result files that exist, so a path outside eval/results cannot be read.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

import duckdb
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from faultline.collectors.dbt_artifacts import Project, load_project
from faultline.lineage.column import ProjectLineage, build_column_lineage
from faultline.lineage.impact import TargetError, impact

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")


@dataclass(frozen=True)
class MCPConfig:
    project_dir: Path
    store: Path
    results_dir: Path


def load_mcp_config(path: Path = Path("faultline.toml")) -> MCPConfig:
    raw = tomllib.loads(path.read_text()).get("mcp", {}) if path.exists() else {}
    return MCPConfig(
        project_dir=Path(raw.get("project_dir", "projects/jaffle_shop")),
        store=Path(raw.get("store", "build/faultline.duckdb")),
        results_dir=Path(raw.get("results_dir", "eval/results")),
    )


@cache
def _project(project_dir: str) -> tuple[Project, ProjectLineage]:
    project = load_project(Path(project_dir))
    return project, build_column_lineage(project)


def _store_rows(store: Path, sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
    if not store.exists():
        return []
    con = duckdb.connect(str(store), read_only=True)
    try:
        return con.execute(sql, params).fetchall()
    except duckdb.CatalogException:
        return []
    finally:
        con.close()


def build_server(config: MCPConfig) -> MCPServer:
    server = MCPServer(
        "faultline",
        instructions=(
            "Read-only access to faultline: triaged dbt incidents with their evidence, "
            "table and column lineage, and benchmark results. Nothing here changes anything."
        ),
    )

    @server.tool(annotations=READ_ONLY)
    def list_incidents(run_id: str | None = None) -> list[dict[str, Any]]:
        """Incidents in the store: key, status (confirmed / not_confirmed), symptoms, top cause."""
        sql = "select incident_key, status, symptoms, top_cause from incidents"
        rows = (
            _store_rows(config.store, sql + " where run_id = ? order by number", [run_id])
            if run_id
            else _store_rows(config.store, sql + " order by incident_key", [])
        )
        return [{"incident": k, "status": s, "symptoms": n, "top_cause": t} for k, s, n, t in rows]

    @server.tool(annotations=READ_ONLY)
    def get_report(incident: str) -> dict[str, Any]:
        """One incident's report: its symptoms, and each cause with its checks and lineage."""
        rows = _store_rows(
            config.store, "select report from incidents where incident_key = ?", [incident]
        )
        if not rows:
            return {"error": f"no incident {incident!r}; call list_incidents"}
        report: dict[str, Any] = json.loads(rows[0][0])
        return report

    @server.tool(annotations=READ_ONLY)
    def get_lineage(
        target: str, direction: Literal["upstream", "downstream"] = "upstream"
    ) -> dict[str, Any]:
        """Lineage of a model, seed or source, or of one column ("model.column"), with paths."""
        project, lineage = _project(str(config.project_dir))
        try:
            result = impact(project, lineage, target, direction)
        except TargetError as exc:
            return {"error": str(exc)}
        return asdict(result)

    @server.tool(annotations=READ_ONLY)
    def impact_of(target: str) -> dict[str, Any]:
        """What breaks if this node or column is wrong: everything downstream, and its tests."""
        project, lineage = _project(str(config.project_dir))
        try:
            result = impact(project, lineage, target, "downstream")
        except TargetError as exc:
            return {"error": str(exc)}
        return {
            "start": result.start,
            "affected": [h.target for h in result.hits],
            "tests_watching": list(result.tests),
        }

    @server.tool(annotations=READ_ONLY)
    def get_results(split: str | None = None, method: str | None = None) -> dict[str, Any]:
        """Benchmark results: without arguments, what exists; with both, that method's metrics."""
        root = config.results_dir
        available = (
            {
                d.name: sorted(p.stem for p in d.glob("*.json") if not p.name.endswith(".run.json"))
                for d in sorted(root.iterdir())
                if d.is_dir()
            }
            if root.is_dir()
            else {}
        )
        if split is None or method is None:
            return {"available": available}
        if not (NAME.match(split) and NAME.match(method)) or method not in available.get(split, []):
            return {"error": "unknown split or method", "available": available}
        doc = json.loads((root / split / f"{method}.json").read_text())
        keep = ("baseline", "split", "command", "config_hash", "metrics", "gating", "cost")
        return {k: doc[k] for k in keep if k in doc}

    return server


def main(config_path: Path = Path("faultline.toml")) -> None:
    build_server(load_mcp_config(config_path)).run("stdio")
