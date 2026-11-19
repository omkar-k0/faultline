"""Monitor tests: each check, property tests, and the reference picker."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from faultline.monitors.core import (
    MonitorConfig,
    detect,
    is_key,
    load_monitor_config,
)
from faultline.monitors.method import pick_references, rank
from tests.conftest import ROOT

CFG = MonitorConfig()


def _profile(
    rows: int = 100, amount_mean: float = 50.0, nulls: int = 0, latest: str = "2026-06-30T12:00:00"
) -> dict[str, Any]:
    return {
        "seed.p.raw": {
            "rows": rows,
            "columns": {
                "id": {
                    "type": "INTEGER",
                    "non_null": rows,
                    "distinct": rows,
                    "min": 1.0,
                    "max": float(rows),
                    "mean": rows / 2,
                    "median": rows / 2,
                },
                "amount": {
                    "type": "DOUBLE",
                    "non_null": rows - nulls,
                    "distinct": 40,
                    "min": 1.0,
                    "max": 99.0,
                    "mean": amount_mean,
                    "median": amount_mean,
                },
                "created": {
                    "type": "TIMESTAMP",
                    "non_null": rows,
                    "distinct": rows,
                    "min": "2026-01-01T00:00:00",
                    "max": latest,
                },
            },
        },
        "model.p.stg": {
            "rows": rows,
            "columns": {
                "id": {
                    "type": "INTEGER",
                    "non_null": rows,
                    "distinct": rows,
                    "min": 1.0,
                    "max": float(rows),
                    "mean": rows / 2,
                    "median": rows / 2,
                }
            },
        },
    }


REFS = [_profile(amount_mean=50.0 + d) for d in (-0.5, -0.2, 0.0, 0.3, 0.6)]


def _monitors(profile: dict[str, Any]) -> set[str]:
    return {a.monitor for a in detect(profile, REFS, CFG)}


def test_clean_profile_raises_nothing() -> None:
    assert detect(_profile(amount_mean=50.1), REFS, CFG) == []


def test_schema_missing_column_and_relation() -> None:
    p = _profile()
    del p["seed.p.raw"]["columns"]["amount"]
    assert "schema" in _monitors(p)
    p = _profile()
    p["model.p.stg"] = {"missing": True}
    found = detect(p, REFS, CFG)
    assert any(
        a.monitor == "schema" and a.node == "model.p.stg" and a.column is None for a in found
    )


def test_type_change() -> None:
    p = _profile()
    p["seed.p.raw"]["columns"]["amount"]["type"] = "VARCHAR"
    assert "schema" in _monitors(p)


def test_volume() -> None:
    assert "volume" in _monitors(_profile(rows=90))
    assert "volume" not in _monitors(_profile(rows=100))


def test_null_rate() -> None:
    assert "null_rate" in _monitors(_profile(nulls=30))
    assert "null_rate" not in _monitors(_profile(nulls=1))


def test_freshness_needs_more_than_the_tolerance() -> None:
    assert "freshness" in _monitors(_profile(latest="2026-06-20T12:00:00"))
    assert "freshness" not in _monitors(_profile(latest="2026-06-30T11:59:00"))
    p = _profile()
    p["seed.p.raw"]["columns"]["created"]["max"] = None
    assert "freshness" in _monitors(p)


def test_time_shift() -> None:
    p = _profile()
    p["seed.p.raw"]["columns"]["created"]["min"] = "2026-01-01T05:00:00"
    p["seed.p.raw"]["columns"]["created"]["max"] = "2026-06-30T17:00:00"
    found = [a for a in detect(p, REFS, CFG) if a.monitor == "time_shift"]
    assert found and found[0].observed == "+5 h"


def test_duplicates_only_on_keys() -> None:
    p = _profile()
    p["seed.p.raw"]["columns"]["id"]["distinct"] = 95
    assert "duplicates" in _monitors(p)
    assert is_key("customer_id") and is_key("ID") and not is_key("amount")


def test_too_few_reference_runs() -> None:
    with pytest.raises(ValueError, match="reference runs"):
        detect(_profile(), REFS[:2], CFG)


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=0, max_value=4))
def test_property_reference_run_against_the_others_is_quiet(i: int) -> None:
    refs = [r for j, r in enumerate(REFS) if j != i]
    assert detect(REFS[i], refs, CFG) == []


@settings(max_examples=50, deadline=None)
@given(st.sampled_from([100.0, 0.01, 3.0]))
def test_property_scaling_a_measure_is_caught(factor: float) -> None:
    p = copy.deepcopy(_profile())
    stats = p["seed.p.raw"]["columns"]["amount"]
    for key in ("mean", "median", "min", "max"):
        stats[key] *= factor
    found = [a for a in detect(p, REFS, CFG) if a.monitor == "distribution"]
    assert found and found[0].column == "amount"


@settings(max_examples=30, deadline=None)
@given(st.sampled_from(["id", "amount", "created"]))
def test_property_removing_any_column_trips_schema(column: str) -> None:
    p = copy.deepcopy(_profile())
    del p["seed.p.raw"]["columns"][column]
    found = [a for a in detect(p, REFS, CFG) if a.monitor == "schema"]
    assert any(a.column == column for a in found)


def test_rank_prefers_upstream() -> None:
    p = _profile()
    p["seed.p.raw"]["columns"]["amount"]["type"] = "VARCHAR"
    p["model.p.stg"]["rows"] = 50
    manifest = {"parent_map": {"model.p.stg": ["seed.p.raw"], "seed.p.raw": []}}
    locs = rank(detect(p, REFS, CFG), manifest)
    assert locs[0].node == "seed.p.raw"


def test_pick_references_hides_who_is_clean() -> None:
    ids = ["c1", "c2", "c3", "c4", "f1", "f2"]
    project = {i: "p" for i in ids}
    refs = pick_references(ids, project, ["c1", "c2", "c3", "c4"])
    assert {len(v) for v in refs.values()} == {3}
    assert all(i not in refs[i] for i in ids)
    assert refs == pick_references(ids, project, ["c1", "c2", "c3", "c4"])


def test_config_from_toml() -> None:
    cfg = load_monitor_config(ROOT / "faultline.toml")
    assert cfg.freshness_min_lag_hours == 1.0 and cfg.min_reference_runs == 3
