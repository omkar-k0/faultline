"""Generate a hand-check sheet: sampled columns with their computed upstream,
plus empty fields for a person to mark each one correct or not.

Sampling is seeded and stratified: an equal share per project, and within a
project a round-robin over lineage kinds so derived and aggregated columns are
not crowded out by direct copies.
"""

from __future__ import annotations

import csv
import io
import random
from collections.abc import Sequence
from dataclasses import dataclass

from faultline.lineage.column import ColumnLineage, ProjectLineage

FIELDS = (
    "id",
    "project",
    "model",
    "column",
    "status",
    "kind",
    "upstream",
    "compiled_sql",
    "correct (y/n)",
    "note",
)


@dataclass(frozen=True)
class SheetRow:
    id: int
    project: str
    model: str
    column: str
    status: str
    kind: str
    upstream: str
    compiled_sql: str

    def values(self) -> list[str]:
        return [
            str(self.id),
            self.project,
            self.model,
            self.column,
            self.status,
            self.kind,
            self.upstream,
            self.compiled_sql,
            "",
            "",
        ]


def _bucket(entry: ColumnLineage) -> str:
    if entry.status != "resolved":
        return entry.status
    kinds = {e.kind for e in entry.upstream}
    for kind in ("aggregated", "derived", "renamed", "direct"):
        if kind in kinds:
            return kind
    return "direct"


def _compiled_path(lineage: ProjectLineage, package: str, original: str | None) -> str:
    if not original:
        return ""
    return str(lineage.project.root / "target" / "compiled" / package / original)


def _short(node_id: str) -> str:
    parts = node_id.split(".")
    return parts[-1] if len(parts) >= 3 else node_id


def _sample_project(lineage: ProjectLineage, n: int, rng: random.Random) -> list[ColumnLineage]:
    buckets: dict[str, list[ColumnLineage]] = {}
    for entry in sorted(lineage.columns.values(), key=lambda e: str(e.target)):
        if entry.target.column == "*":
            continue
        buckets.setdefault(_bucket(entry), []).append(entry)
    for items in buckets.values():
        rng.shuffle(items)
    order = sorted(buckets)
    picked: list[ColumnLineage] = []
    while len(picked) < n and any(buckets.values()):
        for name in order:
            if buckets[name] and len(picked) < n:
                picked.append(buckets[name].pop())
    return picked


def _shares(sizes: Sequence[int], n: int) -> list[int]:
    """Split n across projects as evenly as their sizes allow."""
    shares = [0] * len(sizes)
    remaining = n
    while remaining > 0:
        open_slots = [i for i, size in enumerate(sizes) if shares[i] < size]
        if not open_slots:
            break
        for i in open_slots:
            if remaining == 0:
                break
            shares[i] += 1
            remaining -= 1
    return shares


def build_sheet(lineages: Sequence[ProjectLineage], n: int, seed: int) -> list[SheetRow]:
    rng = random.Random(seed)
    sizes = [sum(1 for ref in lin.columns if ref.column != "*") for lin in lineages]
    rows: list[SheetRow] = []
    for lineage, share in zip(lineages, _shares(sizes, n), strict=True):
        for entry in _sample_project(lineage, share, rng):
            node = lineage.project.nodes[entry.target.node]
            upstream = "; ".join(
                f"{_short(e.source.node)}.{e.source.column} ({e.kind})" for e in entry.upstream
            )
            rows.append(
                SheetRow(
                    id=len(rows) + 1,
                    project=lineage.project.name,
                    model=node.name,
                    column=entry.target.column,
                    status=entry.status,
                    kind=_bucket(entry),
                    upstream=upstream
                    or ("none: literal value" if entry.status == "constant" else ""),
                    compiled_sql=_compiled_path(lineage, node.package, node.original_file_path),
                )
            )
    return rows


def to_csv(rows: Sequence[SheetRow]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(FIELDS)
    for row in rows:
        writer.writerow(row.values())
    return buffer.getvalue()


def to_markdown(rows: Sequence[SheetRow], *, seed: int, projects: Sequence[str]) -> str:
    lines = [
        "# Column lineage hand-check",
        "",
        f"Projects: {', '.join(projects)}. Columns: {len(rows)}. Sampling seed: {seed}.",
        "",
        "Run `make setup` first so the compiled SQL exists.",
        "",
        "For each row, open the compiled SQL, follow the column back one model, and mark",
        "`correct` y or n. A row is correct only if every upstream column is listed, no",
        "extra one is, and the kind is right. Write what is wrong in `note`.",
        "",
        "Rules the lineage follows:",
        "",
        "- Upstream means columns whose values flow into this column, including columns",
        "  inside CASE conditions and a window's PARTITION BY and ORDER BY. Join keys,",
        "  WHERE and GROUP BY columns are not listed.",
        "- Kinds: direct (same name, no change), renamed (only the name changes),",
        "  derived (any expression or window function), aggregated (inside SUM, COUNT,",
        "  MIN, MAX and similar). With several paths, the strongest kind is shown.",
        "- constant: the value is a literal, such as a NULL placeholder or a fixed label.",
        "",
        "| " + " | ".join(FIELDS) + " |",
        "|" + "|".join("---" for _ in FIELDS) + "|",
    ]
    for row in rows:
        cells = [v.replace("|", "\\|") for v in row.values()]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)
