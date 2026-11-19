"""Scorer tests, including the property tests CLAUDE.md asks for."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from faultline.eval.score import Location, Prediction, Truth, aggregate, matches, score_incident

DATA = Truth("i1", "p", "null_spike", "data", "source.p.raw.x", "seed.p.raw_x", "amount", None)
CODE = Truth(
    "i2", "p", "model_logic_bug", "code", "model.p.orders", "model.p.orders", None, "a" * 40
)
CLEAN = Truth("i3", "p", None, None, None, None, None, None)

nodes = st.sampled_from(
    ["model.p.orders", "model.p.stg", "source.p.raw.x", "seed.p.raw_x", "model.p.other"]
)
columns = st.sampled_from([None, "amount", "AMOUNT", "id", "status"])
commits = st.sampled_from([None, "a" * 7, "a" * 40, "b" * 40, "abc"])
locations = st.builds(Location, nodes, columns, commits)


def test_data_fault_needs_node_and_column() -> None:
    assert matches(Location("source.p.raw.x", "amount"), DATA)
    assert matches(Location("seed.p.raw_x", "AMOUNT"), DATA)  # physical node, any case
    assert not matches(Location("source.p.raw.x", None), DATA)
    assert not matches(Location("source.p.raw.x", "id"), DATA)
    assert not matches(Location("model.p.stg", "amount"), DATA)


def test_code_fault_needs_commit() -> None:
    assert matches(Location("model.p.orders", None, "a" * 7), CODE)
    assert matches(Location("model.p.orders", "anything", "a" * 40), CODE)  # truth has no column
    assert not matches(Location("model.p.orders", None, None), CODE)
    assert not matches(Location("model.p.orders", None, "abc"), CODE)  # prefix too short
    assert not matches(Location("model.p.orders", None, "b" * 40), CODE)


@given(st.sampled_from([DATA, CODE]))
def test_property_predicting_the_truth_is_top1(truth: Truth) -> None:
    loc = Location(truth.node or "", truth.column, truth.commit)
    outcome = score_incident(Prediction(True, (loc,)), truth)
    assert outcome.hit_rank == 1 and not outcome.wrong_top1 and outcome.node_hit_rank == 1


@given(st.sampled_from([DATA, CODE]), st.lists(locations, max_size=6))
def test_property_top1_implies_top3_and_ranks_are_bounded(
    truth: Truth, cands: list[Location]
) -> None:
    outcome = score_incident(Prediction(True, tuple(cands)), truth)
    assert outcome.hit_rank is None or 1 <= outcome.hit_rank <= 3
    if outcome.hit_rank is not None:
        assert outcome.node_hit_rank is not None and outcome.node_hit_rank <= outcome.hit_rank
    assert outcome.wrong_top1 == (bool(cands) and outcome.hit_rank != 1)


@given(st.sampled_from([DATA, CODE]), st.lists(locations, max_size=6))
def test_property_only_the_first_three_count(truth: Truth, cands: list[Location]) -> None:
    full = score_incident(Prediction(True, tuple(cands)), truth)
    cut = score_incident(Prediction(True, tuple(cands[:3])), truth)
    assert full.hit_rank == cut.hit_rank


@given(st.lists(locations, max_size=4))
def test_property_undetected_never_scores(cands: list[Location]) -> None:
    for truth in (DATA, CODE):
        outcome = score_incident(Prediction(False, tuple(cands)), truth)
        assert outcome.hit_rank is None and not outcome.detected and not outcome.wrong_top1


@given(st.booleans(), st.lists(locations, max_size=3))
def test_property_clean_runs(detected: bool, cands: list[Location]) -> None:
    outcome = score_incident(Prediction(detected, tuple(cands)), CLEAN)
    assert outcome.false_alarm == detected
    assert outcome.hit_rank is None


def test_fault_type_alone_never_counts() -> None:
    other_place = Location("model.p.other", "amount", "a" * 40)
    assert score_incident(Prediction(True, (other_place,)), DATA).hit_rank is None


def test_not_confirmed_is_counted_separately() -> None:
    outcome = score_incident(Prediction(True, ()), DATA)
    assert outcome.abstained and not outcome.wrong_top1 and outcome.hit_rank is None


def test_aggregate_counts() -> None:
    outcomes = [
        score_incident(Prediction(True, (Location("source.p.raw.x", "amount"),)), DATA),
        score_incident(Prediction(True, ()), CODE),
        score_incident(Prediction(True, ()), CLEAN),
        score_incident(Prediction(False, ()), CLEAN),
    ]
    m = aggregate(outcomes)
    assert m["faulted"]["n"] == 2
    assert m["faulted"]["top1"] == {"count": 1, "n": 2, "rate": 0.5}
    assert m["faulted"]["not_confirmed"]["count"] == 1
    assert m["clean"]["false_alarms"] == {"count": 1, "n": 2, "rate": 0.5}
    assert set(m["by_fault_type"]) == {"null_spike", "model_logic_bug"}
