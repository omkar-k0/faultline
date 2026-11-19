"""Triage tests on a small synthetic pipeline: raw (seed) -> stg -> mart.

Each test changes the run's profile or history the way a fault would and
checks which cause survives its test, or that the answer is "not confirmed".
"""

from __future__ import annotations

import copy
import dataclasses
from pathlib import Path
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from faultline.collectors.dbt_artifacts import Column
from faultline.eval.loader import Commit
from faultline.incidents.manager import group_symptoms
from faultline.incidents.store import IncidentStore
from faultline.lineage.table import build_table_graph
from faultline.monitors.core import MonitorConfig, detect
from faultline.triage.agent import State, Triage
from faultline.triage.evidence import RunContext, Symptom, column_lineage, dbt_symptoms
from faultline.triage.hypotheses import Hypothesis, changes_to, file_matches
from faultline.triage.report import render
from tests.conftest import model, project, table

CFG = MonitorConfig()
RAW = "seed.p.raw"
STG = "model.p.stg"
MART = "model.p.mart"
OTHER = "seed.p.other"

PROJECT = project(
    dataclasses.replace(
        table("raw", ["id", "amount"]),
        columns=(Column("id", "INTEGER"), Column("amount", "INTEGER"), Column("status", "VARCHAR")),
    ),
    table("other", ["code"]),
    model("stg", "select id, amount, status from db.main.raw", [RAW], ["id", "amount", "status"]),
    model(
        "mart",
        "select id, amount * 2 as amount2, case when status = 'x' then 1 else 0 end as is_x "
        "from db.main.stg",
        [STG],
        ["id", "amount2", "is_x"],
    ),
)
CREATE = Commit("a" * 40, "commit 1", ("models/stg.sql", "models/mart.sql"))
CHANGE = Commit("b" * 40, "commit 2", ("models/mart.sql",))


def _num(mean: float, rows: int, non_null: int | None = None) -> dict[str, Any]:
    return {
        "type": "INTEGER",
        "non_null": rows if non_null is None else non_null,
        "distinct": rows,
        "min": 0.0,
        "max": 2 * mean,
        "mean": mean,
        "median": mean,
    }


def _profile(
    shift: float = 0.0,
    rows: int = 100,
    amount_mean: float = 50.0,
    amount_nulls: int = 0,
    is_x_mean: float = 0.3,
    distinct_ids: int | None = None,
) -> dict[str, Any]:
    ids = _num(rows / 2, rows)
    ids["distinct"] = rows if distinct_ids is None else distinct_ids
    amount = _num(amount_mean + shift, rows, rows - amount_nulls)
    status = {"type": "VARCHAR", "non_null": rows, "distinct": 3}
    base = {"id": ids, "amount": amount, "status": status}
    mart = {
        "id": dict(ids),
        "amount2": _num(2 * (amount_mean + shift), rows, rows - amount_nulls),
        "is_x": {**_num(is_x_mean, rows), "distinct": 2, "min": 0.0, "max": 1.0},
    }
    other = {"code": _num(5.0, 10)}
    return {
        RAW: {"rows": rows, "columns": copy.deepcopy(base)},
        STG: {"rows": rows, "columns": copy.deepcopy(base)},
        MART: {"rows": rows, "columns": mart},
        OTHER: {"rows": 10, "columns": other},
    }


REFS = [_profile(shift=d) for d in (-0.5, -0.2, 0.0, 0.3, 0.6)]


def _triage(
    profile: dict[str, Any],
    history: tuple[Commit, ...] = (CREATE,),
    dbt: list[Symptom] | None = None,
) -> Triage:
    _lineage, graph = column_lineage(PROJECT)
    ctx = RunContext(
        run_id="run",
        project=PROJECT,
        tables=build_table_graph(PROJECT),
        columns=graph,
        profile=profile,
        references=REFS,
        history=history,
        skipped=frozenset(),
    )
    return Triage(ctx, detect(profile, REFS, CFG), dbt or [], CFG).run()


def _top(t: Triage) -> Hypothesis | None:
    for report in t.reports:
        if report.ranked:
            return report.ranked[0].hypothesis
    return None


def test_clean_run_is_not_detected() -> None:
    t = _triage(_profile())
    assert not t.prediction().detected and t.reports == []
    assert t.trace == ["gather", "group", "propose", "test", "rank", "report"]
    assert t.state is State.DONE


def test_null_spike_is_traced_to_the_source_column() -> None:
    t = _triage(_profile(amount_nulls=40))
    top = _top(t)
    assert top == Hypothesis("source_column", RAW, "amount")
    cause = t.reports[0].ranked[0]
    assert cause.mode == "observed" and len(cause.explains) >= 3  # raw, stg, mart


def test_duplicate_rows_name_the_key() -> None:
    t = _triage(_profile(rows=120, distinct_ids=100))
    assert _top(t) == Hypothesis("duplicate_rows", RAW, "id")


def test_more_rows_with_new_keys_are_not_duplicates() -> None:
    t = _triage(_profile(rows=120))
    assert all(r.hypothesis.kind != "duplicate_rows" for r in t.reports[0].ranked)
    assert _top(t) is not None and _top(t).node == RAW  # type: ignore[union-attr]


def test_code_change_with_normal_inputs_names_the_commit() -> None:
    p = _profile()
    p[MART]["columns"]["amount2"]["mean"] = 300.0
    t = _triage(p, history=(CREATE, CHANGE))
    assert _top(t) == Hypothesis("code_change", MART, "amount2", CHANGE.hash)


def test_code_change_is_rejected_when_an_input_is_off() -> None:
    p = _profile(amount_nulls=40)
    t = _triage(p, history=(CREATE, CHANGE))
    code = [r for r in t.reports[0].failed if r.hypothesis.kind == "code_change"]
    assert code and all(not c.passed for c in code)
    assert any(ch.name == "every input table is normal" and not ch.passed for ch in code[0].checks)
    assert _top(t) == Hypothesis("source_column", RAW, "amount")


def test_the_commit_that_created_a_file_is_not_a_change() -> None:
    t = _triage(_profile(), history=(CREATE,))
    assert changes_to(t.ctx, MART) == []
    assert file_matches("models/mart.sql", "packages/p/models/mart.sql")
    assert not file_matches("models/mart.sql", "models/mart_v2.sql")


def test_change_through_an_unmeasured_input_is_inferred() -> None:
    t = _triage(_profile(is_x_mean=0.9))
    cause = t.reports[0].ranked[0]
    assert cause.hypothesis == Hypothesis("source_column", RAW, "status")
    assert cause.mode == "inferred" and cause.strength == 0
    assert "[inferred by elimination]" in render(t.report())


def test_not_confirmed_when_no_cause_survives() -> None:
    # A model column is off, nothing changed its code, and its only input is measured and normal.
    p = _profile()
    p[MART]["columns"]["amount2"]["mean"] = 300.0
    t = _triage(p)
    assert t.reports and t.reports[0].status == "not_confirmed"
    prediction = t.prediction()
    assert prediction.detected and prediction.abstained
    assert "not confirmed" in render(t.report())


def test_symptoms_are_grouped_by_lineage() -> None:
    p = _profile(amount_nulls=40)
    p[OTHER]["rows"] = 50
    t = _triage(p)
    groups = group_symptoms(t.ctx, t.symptoms)
    assert len(groups) == 2
    assert groups[0].nodes == (MART, STG, RAW) and groups[1].nodes == (OTHER,)


def test_dbt_failures_become_symptoms_and_skips_do_not() -> None:
    test_node = dataclasses.replace(
        table("t", []),
        unique_id="test.p.unique_stg_id",
        resource_type="test",
        attached_node=STG,
        test_column="id",
        test_name="unique",
    )
    proj = dataclasses.replace(PROJECT, nodes={**PROJECT.nodes, test_node.unique_id: test_node})
    results = {
        "results": [
            {"unique_id": "test.p.unique_stg_id", "status": "fail"},
            {"unique_id": MART, "status": "skipped"},
        ]
    }
    symptoms, skipped = dbt_symptoms(results, proj)
    assert [(s.source, s.node, s.column) for s in symptoms] == [("dbt_test", STG, "id")]
    assert skipped == {MART}


@settings(max_examples=25, deadline=None)
@given(st.sampled_from(["nulls", "shift"]), st.integers(min_value=20, max_value=80))
def test_property_a_source_fault_is_found_at_the_source(kind: str, size: int) -> None:
    """Whatever the size, a change entering at raw.amount is traced back to it."""
    p = _profile(amount_nulls=size) if kind == "nulls" else _profile(amount_mean=50.0 + size)
    t = _triage(p)
    assert _top(t) == Hypothesis("source_column", RAW, "amount")
    assert not t.reports[0].failed or all(not r.passed for r in t.reports[0].failed)


def test_store_round_trip(tmp_path: Path) -> None:
    report = _triage(_profile(amount_nulls=40)).report()
    store = IncidentStore(tmp_path / "f.duckdb")
    keys = store.save(report)
    assert keys == ["run#1"]
    assert store.save(report) == ["run#1"]  # saving again replaces
    got = store.get("run#1")
    assert got is not None and got["status"] == "confirmed" and got["run"] == "run"
    assert store.list("run")[0][1] == "confirmed"
    store.close()
