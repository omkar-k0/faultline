"""Monitors: deterministic checks and statistics on table profiles.

Every check compares one run's profile with reference profiles (known-good
runs of the same pipeline). A value is unusual when it leaves the range the
reference runs covered, widened by a margin. No raw rows and no language model
are involved, and ground truth is never read here.
"""

from __future__ import annotations

import statistics
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

Profile = dict[str, Any]  # node id -> {"rows": n, "columns": {...}} | {"missing": True}

MONITORS = (
    "schema",
    "volume",
    "freshness",
    "null_rate",
    "distribution",
    "duplicates",
    "time_shift",
)
NUMERIC_STATS = ("mean", "median", "min", "max")
TIME_TYPES = ("DATE", "TIMESTAMP", "TIME")


@dataclass(frozen=True)
class MonitorConfig:
    volume_rel_margin: float = 0.01
    volume_abs_margin: int = 1
    null_abs_margin: float = 0.02
    dist_rel_margin: float = 0.10
    dist_mad_k: float = 6.0
    dist_abs_margin: float = 1e-9
    dist_spread_k: float = 1.0
    freshness_min_lag_hours: float = 1.0
    min_reference_runs: int = 3


def load_monitor_config(path: Path = Path("faultline.toml")) -> MonitorConfig:
    raw = tomllib.loads(path.read_text()).get("monitors", {}) if path.is_file() else {}
    defaults = MonitorConfig()
    return MonitorConfig(
        **{k: type(getattr(defaults, k))(v) for k, v in raw.items() if hasattr(defaults, k)}
    )


@dataclass(frozen=True)
class Anomaly:
    monitor: str
    node: str
    column: str | None
    observed: Any
    expected: str
    severity: float  # how far outside the reference band, in band widths; inf for structural


def _present(profile: Profile, node: str) -> bool:
    entry = profile.get(node) or {}
    return "rows" in entry and not entry.get("missing") and not entry.get("error")


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _band(
    values: Sequence[float],
    rel: float,
    abs_margin: float,
    mad_k: float = 0.0,
    spread_k: float = 0.0,
) -> tuple[float, float]:
    """Reference range widened by the largest of: rel * |median|, mad_k * MAD,
    spread_k * (max - min) of the reference values, and abs_margin."""
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values) * 1.4826
    margin = max(rel * abs(med), mad_k * mad, spread_k * (max(values) - min(values)), abs_margin)
    return min(values) - margin, max(values) + margin


def _outside(x: float, lo: float, hi: float) -> float:
    width = max(hi - lo, 1e-12)
    return (lo - x) / width if x < lo else (x - hi) / width if x > hi else 0.0


def check_schema(profile: Profile, refs: Sequence[Profile]) -> list[Anomaly]:
    out: list[Anomaly] = []
    nodes = {n for r in refs for n in r if all(_present(x, n) for x in refs)}
    for node in sorted(nodes):
        if not _present(profile, node):
            out.append(Anomaly("schema", node, None, "missing", "relation present", float("inf")))
            continue
        ref_cols = refs[0][node]["columns"]
        cols = profile[node].get("columns", {})
        for col in sorted(set(ref_cols) - set(cols)):
            out.append(Anomaly("schema", node, col, "missing", "column present", float("inf")))
        for col in sorted(set(cols) - set(ref_cols)):
            out.append(Anomaly("schema", node, col, "new", "column absent", float("inf")))
        for col in sorted(set(cols) & set(ref_cols)):
            if cols[col].get("type") != ref_cols[col].get("type"):
                out.append(
                    Anomaly(
                        "schema",
                        node,
                        col,
                        cols[col].get("type"),
                        str(ref_cols[col].get("type")),
                        float("inf"),
                    )
                )
    return out


def _shared(profile: Profile, refs: Sequence[Profile]) -> list[str]:
    return sorted(n for n in refs[0] if _present(profile, n) and all(_present(r, n) for r in refs))


def check_volume(profile: Profile, refs: Sequence[Profile], cfg: MonitorConfig) -> list[Anomaly]:
    out = []
    for node in _shared(profile, refs):
        values = [float(r[node]["rows"]) for r in refs]
        lo, hi = _band(values, cfg.volume_rel_margin, cfg.volume_abs_margin)
        rows = float(profile[node]["rows"])
        sev = _outside(rows, lo, hi)
        if sev > 0:
            out.append(Anomaly("volume", node, None, int(rows), f"{lo:.0f}..{hi:.0f}", sev))
    return out


def _columns(profile: Profile, refs: Sequence[Profile], node: str) -> list[str]:
    cols = profile[node].get("columns", {})
    return sorted(c for c in cols if all(c in r[node].get("columns", {}) for r in refs))


def _null_share(entry: dict[str, Any], col: str) -> float | None:
    rows = entry.get("rows") or 0
    non_null = entry["columns"][col].get("non_null")
    return None if not rows or non_null is None else 1.0 - non_null / rows


def check_null_rate(profile: Profile, refs: Sequence[Profile], cfg: MonitorConfig) -> list[Anomaly]:
    out = []
    for node in _shared(profile, refs):
        for col in _columns(profile, refs, node):
            ref_shares = [_null_share(r[node], col) for r in refs]
            share = _null_share(profile[node], col)
            if share is None or any(s is None for s in ref_shares):
                continue
            ceiling = max(s for s in ref_shares if s is not None) + cfg.null_abs_margin
            if share > ceiling:
                sev = (share - ceiling) / max(cfg.null_abs_margin, 1e-9)
                out.append(
                    Anomaly("null_rate", node, col, round(share, 4), f"<= {ceiling:.4f}", sev)
                )
    return out


def check_distribution(
    profile: Profile, refs: Sequence[Profile], cfg: MonitorConfig
) -> list[Anomaly]:
    out = []
    for node in _shared(profile, refs):
        for col in _columns(profile, refs, node):
            stats = profile[node]["columns"][col]
            worst: tuple[float, str, float, str] | None = None
            for stat in NUMERIC_STATS:
                x = _num(stats.get(stat))
                values = [_num(r[node]["columns"][col].get(stat)) for r in refs]
                if x is None or any(v is None for v in values):
                    continue
                vals = [v for v in values if v is not None]
                lo, hi = _band(
                    vals,
                    cfg.dist_rel_margin,
                    cfg.dist_abs_margin,
                    cfg.dist_mad_k,
                    cfg.dist_spread_k,
                )
                sev = _outside(x, lo, hi)
                if sev > 0 and (worst is None or sev > worst[0]):
                    worst = (sev, stat, x, f"{lo:.6g}..{hi:.6g}")
            if worst:
                out.append(
                    Anomaly(
                        "distribution", node, col, f"{worst[1]}={worst[2]:.6g}", worst[3], worst[0]
                    )
                )
    return out


def is_key(column: str) -> bool:
    """Key columns by name: `id` or `*_id`. A measure that happens to be unique is not a key."""
    lowered = column.lower()
    return lowered == "id" or lowered.endswith("_id")


def check_duplicates(profile: Profile, refs: Sequence[Profile]) -> list[Anomaly]:
    out = []
    for node in _shared(profile, refs):
        for col in _columns(profile, refs, node):
            if not is_key(col):
                continue
            if not all(
                r[node]["rows"] > 1 and r[node]["columns"][col].get("distinct") == r[node]["rows"]
                for r in refs
            ):
                continue
            entry = profile[node]
            distinct, rows = entry["columns"][col].get("distinct"), entry.get("rows")
            if isinstance(distinct, int) and isinstance(rows, int) and distinct < rows:
                out.append(
                    Anomaly(
                        "duplicates",
                        node,
                        col,
                        f"{distinct} distinct / {rows} rows",
                        "unique",
                        float(rows - distinct),
                    )
                )
    return out


def _is_time(col_stats: dict[str, Any]) -> bool:
    return str(col_stats.get("type", "")).upper().startswith(TIME_TYPES)


def check_freshness_and_shift(
    profile: Profile, refs: Sequence[Profile], cfg: MonitorConfig
) -> list[Anomaly]:
    out = []
    for node in _shared(profile, refs):
        for col in _columns(profile, refs, node):
            stats = profile[node]["columns"][col]
            if not _is_time(stats):
                continue
            ref_max = [_time(r[node]["columns"][col].get("max")) for r in refs]
            ref_min = [_time(r[node]["columns"][col].get("min")) for r in refs]
            if any(v is None for v in ref_max + ref_min):
                continue
            rmax = [v for v in ref_max if v is not None]
            rmin = [v for v in ref_min if v is not None]
            obs_max, obs_min = _time(stats.get("max")), _time(stats.get("min"))
            if obs_max is None:
                out.append(
                    Anomaly(
                        "freshness", node, col, None, f">= {min(rmax).isoformat()}", float("inf")
                    )
                )
                continue
            lag = (min(rmax) - obs_max).total_seconds() / 3600
            if lag > cfg.freshness_min_lag_hours:
                out.append(
                    Anomaly(
                        "freshness",
                        node,
                        col,
                        obs_max.isoformat(),
                        f">= {min(rmax).isoformat()}",
                        lag,
                    )
                )
                continue
            if obs_min is None or len(set(rmax)) > 1 or len(set(rmin)) > 1:
                continue
            d_max, d_min = obs_max - rmax[0], obs_min - rmin[0]
            if d_max == d_min and d_max.total_seconds() != 0:
                hours = d_max.total_seconds() / 3600
                out.append(
                    Anomaly("time_shift", node, col, f"{hours:+g} h", "no shift", abs(hours))
                )
    return out


def detect(
    profile: Profile, refs: Sequence[Profile], cfg: MonitorConfig | None = None
) -> list[Anomaly]:
    """All anomalies of one run against its reference runs."""
    cfg = cfg or MonitorConfig()
    if len(refs) < cfg.min_reference_runs:
        raise ValueError(f"need at least {cfg.min_reference_runs} reference runs, got {len(refs)}")
    return [
        *check_schema(profile, refs),
        *check_volume(profile, refs, cfg),
        *check_freshness_and_shift(profile, refs, cfg),
        *check_null_rate(profile, refs, cfg),
        *check_distribution(profile, refs, cfg),
        *check_duplicates(profile, refs),
    ]
