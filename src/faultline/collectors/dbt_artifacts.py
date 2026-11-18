"""Load dbt artefacts (manifest.json, catalog.json) into typed records.

Only metadata and compiled code are read. No warehouse rows are touched.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SUPPORTED_MANIFEST = frozenset({"v12"})
SUPPORTED_CATALOG = frozenset({"v1"})

NODE_TYPES = frozenset({"model", "seed", "snapshot", "test"})


class ArtifactError(RuntimeError):
    """A dbt artefact is missing, unreadable or of an unsupported version."""


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str | None = None


@dataclass(frozen=True)
class Node:
    unique_id: str
    resource_type: str
    name: str
    package: str
    database: str | None
    schema: str | None
    identifier: str | None
    materialized: str | None
    depends_on: tuple[str, ...]
    compiled_code: str | None
    original_file_path: str | None
    columns: tuple[Column, ...] = ()
    # For tests: the node and column the test is attached to.
    attached_node: str | None = None
    test_column: str | None = None

    @property
    def is_ephemeral(self) -> bool:
        return self.materialized == "ephemeral"

    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    adapter_type: str
    dbt_version: str
    nodes: Mapping[str, Node] = field(default_factory=dict)

    def by_type(self, *resource_types: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.resource_type in resource_types]

    @property
    def models(self) -> list[Node]:
        return self.by_type("model")

    @property
    def tests(self) -> list[Node]:
        return self.by_type("test")


def _schema_version(doc: Mapping[str, Any], path: Path) -> str:
    try:
        url = str(doc["metadata"]["dbt_schema_version"])
    except (KeyError, TypeError) as exc:
        raise ArtifactError(f"{path}: no metadata.dbt_schema_version") from exc
    return url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".json")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ArtifactError(f"{path} not found: run `make build-projects` first")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ArtifactError(f"{path}: expected a JSON object")
    return data


def _catalog_columns(entry: Mapping[str, Any] | None) -> tuple[Column, ...]:
    if not entry:
        return ()
    cols = sorted(entry.get("columns", {}).values(), key=lambda c: int(c.get("index", 0)))
    return tuple(Column(name=str(c["name"]), data_type=c.get("type")) for c in cols)


def _node(raw: Mapping[str, Any], catalog_entry: Mapping[str, Any] | None) -> Node:
    resource_type = str(raw["resource_type"])
    config = raw.get("config") or {}
    test_meta = raw.get("test_metadata") or {}
    kwargs = test_meta.get("kwargs") or {}
    test_column = raw.get("column_name") or kwargs.get("column_name")
    identifier = raw.get("identifier") if resource_type == "source" else raw.get("alias")
    return Node(
        unique_id=str(raw["unique_id"]),
        resource_type=resource_type,
        name=str(raw["name"]),
        package=str(raw.get("package_name", "")),
        database=raw.get("database"),
        schema=raw.get("schema"),
        identifier=identifier or raw.get("name"),
        materialized=config.get("materialized"),
        depends_on=tuple((raw.get("depends_on") or {}).get("nodes", [])),
        compiled_code=raw.get("compiled_code"),
        original_file_path=raw.get("original_file_path"),
        columns=_catalog_columns(catalog_entry),
        attached_node=raw.get("attached_node"),
        test_column=str(test_column) if test_column else None,
    )


def load_project(project_dir: Path, target: str = "target") -> Project:
    """Read `<project_dir>/<target>/manifest.json` and `catalog.json`."""
    target_dir = project_dir / target
    manifest_path = target_dir / "manifest.json"
    catalog_path = target_dir / "catalog.json"
    manifest = _read_json(manifest_path)
    catalog = _read_json(catalog_path)

    mv = _schema_version(manifest, manifest_path)
    if mv not in SUPPORTED_MANIFEST:
        raise ArtifactError(f"{manifest_path}: manifest {mv} not supported ({SUPPORTED_MANIFEST})")
    cv = _schema_version(catalog, catalog_path)
    if cv not in SUPPORTED_CATALOG:
        raise ArtifactError(f"{catalog_path}: catalog {cv} not supported ({SUPPORTED_CATALOG})")

    cat_nodes: Mapping[str, Any] = catalog.get("nodes", {})
    cat_sources: Mapping[str, Any] = catalog.get("sources", {})

    nodes: dict[str, Node] = {}
    for uid, raw in manifest.get("nodes", {}).items():
        if raw.get("resource_type") in NODE_TYPES:
            nodes[uid] = _node(raw, cat_nodes.get(uid))
    for uid, raw in manifest.get("sources", {}).items():
        nodes[uid] = _node(raw, cat_sources.get(uid))

    meta = manifest.get("metadata", {})
    return Project(
        name=project_dir.name,
        root=project_dir,
        adapter_type=str(meta.get("adapter_type", "")),
        dbt_version=str(meta.get("dbt_version", "")),
        nodes=nodes,
    )
