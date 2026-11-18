"""The eight fault types.

Data faults rewrite a seed file. Code faults edit one model's SQL and commit
the change in the workspace's git history, so ground truth can name the commit.
Every fault returns its exact location and parameters; nothing is guessed.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from faultline.inject.catalog import FaultCatalog, Seed, SeedColumn, parse_date, parse_timestamp
from faultline.inject.workspace import git_commit, read_csv, write_csv

FaultType = Literal[
    "schema_change",
    "late_or_missing_data",
    "duplicate_keys",
    "null_spike",
    "distribution_shift",
    "model_logic_bug",
    "broken_join",
    "timezone_error",
]
FAULT_TYPES: tuple[FaultType, ...] = (
    "schema_change",
    "late_or_missing_data",
    "duplicate_keys",
    "null_spike",
    "distribution_shift",
    "model_logic_bug",
    "broken_join",
    "timezone_error",
)
FaultClass = Literal["data", "code"]
CODE_FAULTS: frozenset[FaultType] = frozenset({"model_logic_bug", "broken_join"})


@dataclass(frozen=True)
class Candidate:
    fault_type: FaultType
    physical: str  # seed node id or model node id
    column: str | None = None
    site: tuple[str, int] | None = None  # code faults: (operator name, match index)


@dataclass(frozen=True)
class Location:
    node: str  # the node models read (source or seed) or the faulted model
    physical: str  # where the change was written: seed node or model node
    file: str
    column: str | None
    commit: str | None


@dataclass(frozen=True)
class Applied:
    fault_type: FaultType
    fault_class: FaultClass
    params: dict[str, Any] = field(default_factory=dict)
    location: Location | None = None


# ---------------------------------------------------------------- data faults


def _columns(
    catalog: FaultCatalog, nodes: set[str], pred: Callable[[Seed, SeedColumn], bool]
) -> list[Candidate]:
    return [
        Candidate("schema_change", s.node, c.column)  # fault type replaced by caller
        for s in catalog.seeds
        if s.node in nodes
        for c in s.columns
        if pred(s, c)
    ]


def _retag(cands: list[Candidate], fault_type: FaultType) -> list[Candidate]:
    return [Candidate(fault_type, c.physical, c.column, c.site) for c in cands]


def _data_location(catalog: FaultCatalog, seed_node: str, column: str | None) -> Location:
    seed = catalog.seed(seed_node)
    return Location(seed.relation, seed.node, seed.file, column, None)


def _load(
    ws: Path, catalog: FaultCatalog, cand: Candidate
) -> tuple[Seed, Path, list[str], list[list[str]], int]:
    seed = catalog.seed(cand.physical)
    path = ws / seed.file
    header, rows = read_csv(path)
    idx = header.index(cand.column) if cand.column else -1
    return seed, path, header, rows, idx


def _pick(rng: random.Random, n: int, fraction: float, pool: list[int]) -> list[int]:
    k = min(len(pool), max(1, round(n * fraction)))
    return sorted(rng.sample(pool, k))


SCHEMA_SUFFIXES = ("_v2", "_new", "_value", "_raw")


def cands_schema_change(catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    return _retag(
        _columns(catalog, nodes, lambda s, c: c.read_downstream and c.role != "empty"),
        "schema_change",
    )


def apply_schema_change(
    ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random
) -> Applied:
    seed, path, header, rows, idx = _load(ws, catalog, cand)
    role = seed.column(cand.column or "").role
    ops = ["rename", "drop"] + (["retype"] if role == "numeric" else [])
    op = rng.choice(ops)
    params: dict[str, Any] = {"op": op}
    if op == "rename":
        new = header[idx] + rng.choice(SCHEMA_SUFFIXES)
        header[idx] = new
        params["new_name"] = new
    elif op == "drop":
        del header[idx]
        for row in rows:
            if idx < len(row):
                del row[idx]
    else:
        for row in rows:
            if row[idx] != "":
                row[idx] = f"{row[idx]} units"
        params["new_type"] = "text"
    write_csv(path, header, rows)
    return Applied(
        "schema_change", "data", params, _data_location(catalog, cand.physical, cand.column)
    )


def cands_late_or_missing(catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    late = _columns(
        catalog,
        nodes,
        lambda s, c: (
            s.rows >= 3
            and c.read_downstream
            and c.role in {"date", "timestamp"}
            and c.fill_rate >= 0.5
        ),
    )
    missing = [
        Candidate("late_or_missing_data", s.node, None)
        for s in catalog.seeds
        if s.node in nodes and s.rows >= 1 and any(c.read_downstream for c in s.columns)
    ]
    return _retag(late, "late_or_missing_data") + missing


def _when(value: str) -> Any:
    return parse_timestamp(value) or parse_date(value)


def apply_late_or_missing(
    ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random
) -> Applied:
    _seed, path, header, rows, idx = _load(ws, catalog, cand)
    if cand.column is None:
        write_csv(path, header, [])
        return Applied(
            "late_or_missing_data",
            "data",
            {"variant": "missing", "rows_removed": len(rows)},
            _data_location(catalog, cand.physical, None),
        )
    dated = sorted({_when(r[idx]) for r in rows if r[idx] and _when(r[idx])})
    if len(dated) < 2:
        cutoff = dated[-1]
    else:
        q = rng.uniform(0.6, 0.85)
        cutoff = dated[min(len(dated) - 1, max(1, int(len(dated) * q)))]
    kept = [r for r in rows if not (r[idx] and _when(r[idx]) and _when(r[idx]) >= cutoff)]
    if len(kept) == len(rows):  # always remove at least the newest rows
        kept = [r for r in rows if not (r[idx] and _when(r[idx]) == dated[-1])]
    write_csv(path, header, kept)
    params = {
        "variant": "late",
        "cutoff": cutoff.isoformat(sep=" "),
        "rows_removed": len(rows) - len(kept),
    }
    return Applied(
        "late_or_missing_data", "data", params, _data_location(catalog, cand.physical, cand.column)
    )


def _is_primary_key(seed: Seed, col: SeedColumn) -> bool:
    """`id`, or the first column when it is a unique key (e.g. balance_transaction_id)."""
    first = seed.columns[0].column if seed.columns else None
    return col.role == "key" and col.unique and (col.column.lower() == "id" or col.column == first)


def cands_duplicate_keys(catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    return _retag(
        _columns(
            catalog, nodes, lambda s, c: s.rows >= 2 and c.read_downstream and _is_primary_key(s, c)
        ),
        "duplicate_keys",
    )


def apply_duplicate_keys(
    ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random
) -> Applied:
    _seed, path, header, rows, _idx = _load(ws, catalog, cand)
    picked = _pick(rng, len(rows), rng.uniform(0.05, 0.2), list(range(len(rows))))
    write_csv(path, header, rows + [list(rows[i]) for i in picked])
    params = {"rows_duplicated": len(picked)}
    return Applied(
        "duplicate_keys", "data", params, _data_location(catalog, cand.physical, cand.column)
    )


def cands_null_spike(catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    return _retag(
        _columns(
            catalog,
            nodes,
            lambda s, c: (
                s.rows >= 3
                and c.read_downstream
                and c.role not in {"key", "empty"}
                and c.fill_rate >= 0.8
            ),
        ),
        "null_spike",
    )


def apply_null_spike(
    ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random
) -> Applied:
    _seed, path, header, rows, idx = _load(ws, catalog, cand)
    present = [i for i, r in enumerate(rows) if r[idx] != ""]
    picked = _pick(rng, len(rows), rng.uniform(0.3, 0.7), present)
    for i in picked:
        rows[i][idx] = ""
    write_csv(path, header, rows)
    params = {"rows_nulled": len(picked), "fraction": round(len(picked) / len(rows), 4)}
    return Applied(
        "null_spike", "data", params, _data_location(catalog, cand.physical, cand.column)
    )


def cands_distribution_shift(catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    return _retag(
        _columns(
            catalog,
            nodes,
            lambda s, c: (
                s.rows >= 3
                and c.read_downstream
                and c.role in {"numeric", "categorical"}
                and c.fill_rate >= 0.5
            ),
        ),
        "distribution_shift",
    )


def apply_distribution_shift(
    ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random
) -> Applied:
    seed, path, header, rows, idx = _load(ws, catalog, cand)
    role = seed.column(cand.column or "").role
    params: dict[str, Any]
    if role == "numeric":
        factor = rng.choice([100.0, 0.01, round(rng.uniform(1.5, 3.0), 3)])
        for row in rows:
            v = row[idx]
            if v == "":
                continue
            if "." in v:
                row[idx] = f"{float(v) * factor:.{len(v.split('.', 1)[1])}f}"
            else:
                row[idx] = str(round(int(v) * factor))
        params = {"variant": "scale", "factor": factor}
    else:
        values = sorted({r[idx] for r in rows if r[idx] != ""})
        target = rng.choice(values)
        pool = [i for i, r in enumerate(rows) if r[idx] not in ("", target)]
        picked = _pick(rng, len(pool), rng.uniform(0.4, 0.8), pool) if pool else []
        for i in picked:
            rows[i][idx] = target
        params = {"variant": "category_mix", "target": target, "rows_changed": len(picked)}
    write_csv(path, header, rows)
    return Applied(
        "distribution_shift", "data", params, _data_location(catalog, cand.physical, cand.column)
    )


def cands_timezone(catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    return _retag(
        _columns(
            catalog,
            nodes,
            lambda s, c: (
                c.read_downstream and c.role in {"timestamp", "date"} and c.fill_rate >= 0.5
            ),
        ),
        "timezone_error",
    )


def apply_timezone(ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random) -> Applied:
    seed, path, header, rows, idx = _load(ws, catalog, cand)
    hours = rng.choice([h for h in range(-9, 10) if h not in (0,)])
    role = seed.column(cand.column or "").role
    changed = 0
    if role == "timestamp":
        for row in rows:
            ts = parse_timestamp(row[idx]) if row[idx] else None
            if ts:
                row[idx] = (ts + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
                changed += 1
    else:
        # A date column only moves where the shift crosses midnight: a share |h|/24 of rows.
        present = [i for i, r in enumerate(rows) if r[idx] != ""]
        picked = _pick(rng, len(present), abs(hours) / 24, present)
        step = timedelta(days=1 if hours > 0 else -1)
        for i in picked:
            d = parse_date(rows[i][idx])
            if d:
                rows[i][idx] = (d + step).strftime("%Y-%m-%d")
                changed += 1
    write_csv(path, header, rows)
    params = {"variant": "data", "hours": hours, "rows_changed": changed}
    return Applied(
        "timezone_error", "data", params, _data_location(catalog, cand.physical, cand.column)
    )


# ---------------------------------------------------------------- code faults

_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}|--[^\n]*", re.DOTALL)

LOGIC_OPERATORS: dict[str, tuple[str, str]] = {
    "sum_to_avg": (r"\bsum\s*\(", "avg("),
    "min_to_max": (r"\bmin\s*\(", "max("),
    "max_to_min": (r"\bmax\s*\(", "min("),
    "count_to_count_distinct": (r"\bcount\s*\(\s*(?!distinct\b|\*)", "count(distinct "),
    "gte_to_gt": (r">=", ">"),
    "lte_to_lt": (r"<=", "<"),
    "coalesce_zero_to_one": (r"(coalesce\s*\([^(),]+,\s*)0(\s*\))", r"\g<1>1\g<2>"),
    "divide_by_100_to_10": (r"/\s*100\b", "/ 10"),
    "plus_to_minus": (r"(?<=[\w\)])\s\+\s(?=[\w\(])", " - "),
}
JOIN_OPERATORS: dict[str, tuple[str, str]] = {
    "left_to_inner_join": (r"\bleft\s+(?:outer\s+)?join\b", "inner join"),
    "inner_to_left_join": (r"\binner\s+join\b", "left join"),
    "join_condition_always_true": (
        r"(\bon\s+)([\w\.\"]+)(\s*=\s*)([\w\.\"]+)",
        r"\g<1>\g<2>\g<3>\g<2>",
    ),
}


def _masked(text: str) -> str:
    """Replace Jinja blocks and SQL comments with spaces so operators skip them."""
    return _JINJA.sub(lambda m: " " * len(m.group(0)), text)


def _matches(text: str, pattern: str) -> list[re.Match[str]]:
    return list(re.finditer(pattern, _masked(text), flags=re.IGNORECASE))


def _code_cands(
    catalog: FaultCatalog, nodes: set[str], ops: dict[str, tuple[str, str]], fault_type: FaultType
) -> list[Candidate]:
    out: list[Candidate] = []
    for site in catalog.models:
        if site.node not in nodes:
            continue
        text = (catalog.project_dir / site.file).read_text()
        for name, (pattern, _) in ops.items():
            for i, _m in enumerate(_matches(text, pattern)):
                out.append(Candidate(fault_type, site.node, None, (name, i)))
    return out


def _output_column(text: str, pos: int, columns: tuple[str, ...]) -> str | None:
    """The output alias of the select item containing `pos`, if it is a model column."""
    masked = _masked(text)
    depth = 0
    end = len(masked)
    for j in range(pos, len(masked)):
        ch = masked[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                end = j
                break
            depth -= 1
        elif depth == 0 and (ch == "," or re.match(r"\s+from\b", masked[j : j + 6], re.I)):
            end = j
            break
    alias = re.findall(r"\bas\s+\"?(\w+)\"?", masked[pos:end], flags=re.IGNORECASE)
    if alias and alias[-1].lower() in {c.lower() for c in columns}:
        return next(c for c in columns if c.lower() == alias[-1].lower())
    return None


def _apply_code(
    ws: Path,
    catalog: FaultCatalog,
    cand: Candidate,
    ops: dict[str, tuple[str, str]],
    fault_type: FaultType,
) -> Applied:
    assert cand.site is not None
    name, index = cand.site
    site = next(m for m in catalog.models if m.node == cand.physical)
    path = ws / site.file
    text = path.read_text()
    pattern, replacement = ops[name]
    match = _matches(text, pattern)[index]
    original = text[match.start() : match.end()]
    replaced = re.sub(pattern, replacement, original, count=1, flags=re.IGNORECASE)
    path.write_text(text[: match.start()] + replaced + text[match.end() :])
    column = _output_column(text, match.start(), catalog.model_columns.get(site.node, ()))
    commit = git_commit(ws, f"inject: {name} in {site.node}")
    line = text.count("\n", 0, match.start()) + 1
    params = {"operator": name, "line": line, "before": original.strip(), "after": replaced.strip()}
    location = Location(site.node, site.node, site.file, column, commit)
    return Applied(fault_type, "code", params, location)


def cands_logic_bug(catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    return _code_cands(catalog, nodes, LOGIC_OPERATORS, "model_logic_bug")


def apply_logic_bug(
    ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random
) -> Applied:
    return _apply_code(ws, catalog, cand, LOGIC_OPERATORS, "model_logic_bug")


def cands_broken_join(catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    return _code_cands(catalog, nodes, JOIN_OPERATORS, "broken_join")


def apply_broken_join(
    ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random
) -> Applied:
    applied = _apply_code(ws, catalog, cand, JOIN_OPERATORS, "broken_join")
    assert applied.location is not None
    loc = applied.location
    # A join fault breaks rows, not one column: location is the node and commit.
    return Applied(
        applied.fault_type,
        "code",
        applied.params,
        Location(loc.node, loc.physical, loc.file, None, loc.commit),
    )


FaultFns = tuple[
    Callable[[FaultCatalog, set[str]], list[Candidate]],
    Callable[[Path, FaultCatalog, Candidate, random.Random], Applied],
]
REGISTRY: dict[FaultType, FaultFns] = {
    "schema_change": (cands_schema_change, apply_schema_change),
    "late_or_missing_data": (cands_late_or_missing, apply_late_or_missing),
    "duplicate_keys": (cands_duplicate_keys, apply_duplicate_keys),
    "null_spike": (cands_null_spike, apply_null_spike),
    "distribution_shift": (cands_distribution_shift, apply_distribution_shift),
    "model_logic_bug": (cands_logic_bug, apply_logic_bug),
    "broken_join": (cands_broken_join, apply_broken_join),
    "timezone_error": (cands_timezone, apply_timezone),
}


def candidates(fault_type: FaultType, catalog: FaultCatalog, nodes: set[str]) -> list[Candidate]:
    return REGISTRY[fault_type][0](catalog, nodes)


def apply(ws: Path, catalog: FaultCatalog, cand: Candidate, rng: random.Random) -> Applied:
    applied = REGISTRY[cand.fault_type][1](ws, catalog, cand, rng)
    if applied.fault_class == "data":
        git_commit(ws, f"inject: {cand.fault_type} in {cand.physical}")
    return applied
