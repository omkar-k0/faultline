"""Fault injector tests. No dbt runs: faults are applied to workspaces only.

The core property (CLAUDE.md): an injected fault is recoverable from its
ground truth. Diffing a faulted workspace against a clean one prepared from the
same seed finds exactly the recorded location and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from faultline.inject import faults
from faultline.inject.catalog import FaultCatalog, build_catalog, infer_role
from faultline.inject.faults import CODE_FAULTS, FAULT_TYPES, FaultType
from faultline.inject.incident import IncidentSpec, inject_only, prepare
from faultline.inject.workspace import git_changed_files, read_csv, tree_hash
from tests.conftest import PROJECTS

ROW_FAULTS = {"late_or_missing_data", "duplicate_keys"}


@pytest.fixture(scope="module")
def catalogs() -> dict[str, FaultCatalog]:
    return {p: build_catalog(PROJECTS / p) for p in ("jaffle_shop", "stripe")}


def _all_nodes(cat: FaultCatalog) -> set[str]:
    return {s.node for s in cat.seeds} | {m.node for m in cat.models}


def _csv_diff(clean: Path, faulted: Path) -> tuple[set[str], bool, bool]:
    """(changed columns, rows added or removed, header changed)."""
    h1, r1 = read_csv(clean)
    h2, r2 = read_csv(faulted)
    if h1 != h2:
        return (
            set(h1) ^ set(h2) | ({a for a, b in zip(h1, h2, strict=False) if a != b}),
            len(r1) != len(r2),
            True,
        )
    if len(r1) != len(r2):
        return set(), True, False
    cols = {h1[i] for a, b in zip(r1, r2, strict=True) for i in range(len(h1)) if a[i] != b[i]}
    return cols, False, False


def _files_differ(a: Path, b: Path) -> list[str]:
    out = []
    for path in sorted(p for p in a.rglob("*") if p.is_file() and ".git" not in p.parts):
        rel = path.relative_to(a)
        other = b / rel
        if not other.is_file() or other.read_bytes() != path.read_bytes():
            out.append(str(rel))
    return out


def test_role_inference() -> None:
    assert infer_role("customer_id", ["1", "2"]) == "key"
    assert infer_role("created", ["2021-01-01 10:00:00", ""]) == "timestamp"
    assert infer_role("order_date", ["2018-01-01"]) == "date"
    assert infer_role("amount", ["10", "-2.5"]) == "numeric"
    assert infer_role("paid", ["TRUE", "false"]) == "boolean"
    assert infer_role("x", ["", ""]) == "empty"


def test_every_fault_type_has_candidates_somewhere(catalogs: dict[str, FaultCatalog]) -> None:
    for fault_type in FAULT_TYPES:
        assert any(faults.candidates(fault_type, c, _all_nodes(c)) for c in catalogs.values()), (
            fault_type
        )


def test_jaffle_parent_seed(catalogs: dict[str, FaultCatalog]) -> None:
    cat = catalogs["jaffle_shop"]
    assert {s.node for s in cat.seeds if s.is_parent} == {"seed.jaffle_shop.raw_customers"}


def test_prepare_is_deterministic(catalogs: dict[str, FaultCatalog], tmp_path: Path) -> None:
    cat = catalogs["stripe"]
    spec = IncidentSpec("x", "stripe", "t", 5, None)
    a, ca = prepare(cat, tmp_path / "a", spec)
    b, cb = prepare(cat, tmp_path / "b", spec)
    c, _ = prepare(cat, tmp_path / "c", IncidentSpec("x", "stripe", "t", 6, None))
    assert tree_hash(a) == tree_hash(b)
    assert ca == cb  # fixed author and date: same commit hash
    assert tree_hash(a) != tree_hash(c)


def test_resample_changes_only_numeric_measures(
    catalogs: dict[str, FaultCatalog], tmp_path: Path
) -> None:
    cat = catalogs["jaffle_shop"]
    ws, _ = prepare(cat, tmp_path / "ws", IncidentSpec("x", "jaffle_shop", "t", 1, None))
    for seed in cat.seeds:
        cols, rows_changed, header_changed = _csv_diff(cat.project_dir / seed.file, ws / seed.file)
        assert not rows_changed and not header_changed
        assert cols <= {c.column for c in seed.columns if c.role == "numeric"}


def _check_recoverable(cat: FaultCatalog, fault_type: FaultType, seed: int, root: Path) -> None:
    spec = IncidentSpec("p", cat.project, "t", seed, fault_type)
    clean, _ = prepare(cat, root / "clean", IncidentSpec("p", cat.project, "t", seed, None))
    ws, clean_commit, applied = inject_only(cat, root / "faulted", spec, _all_nodes(cat))
    assert applied is not None and applied.location is not None
    loc = applied.location
    changed = [f for f in _files_differ(clean, ws) if f != ".gitignore"]
    assert changed == [loc.file], (fault_type, changed, loc)

    if fault_type in CODE_FAULTS:
        assert loc.commit is not None
        assert git_changed_files(ws, clean_commit, loc.commit) == [loc.file]
        assert loc.node == loc.physical and loc.node.startswith("model.")
        return

    assert loc.commit is None
    seed_meta = cat.seed(loc.physical)
    assert loc.node == seed_meta.relation
    cols, rows_changed, header_changed = _csv_diff(clean / loc.file, ws / loc.file)
    params = applied.params
    if fault_type == "schema_change":
        assert header_changed or cols == {loc.column}
        if params["op"] == "retype":
            assert cols == {loc.column}
        else:
            assert loc.column in cols
    elif fault_type in ROW_FAULTS:
        assert rows_changed and not header_changed and not cols
        _, rows_clean = read_csv(clean / loc.file)
        _, rows_faulted = read_csv(ws / loc.file)
        if fault_type == "duplicate_keys":
            assert len(rows_faulted) - len(rows_clean) == params["rows_duplicated"]
            assert rows_faulted[: len(rows_clean)] == rows_clean
        else:
            assert len(rows_clean) - len(rows_faulted) == params["rows_removed"] > 0
            assert all(r in rows_clean for r in rows_faulted)
    else:
        assert cols == {loc.column}, (fault_type, cols, loc)


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    project=st.sampled_from(["jaffle_shop", "stripe"]),
    fault_type=st.sampled_from(FAULT_TYPES),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_property_fault_is_recoverable_from_ground_truth(
    catalogs: dict[str, FaultCatalog],
    tmp_path_factory: pytest.TempPathFactory,
    project: str,
    fault_type: FaultType,
    seed: int,
) -> None:
    cat = catalogs[project]
    if not faults.candidates(fault_type, cat, _all_nodes(cat)):
        return
    _check_recoverable(cat, fault_type, seed, tmp_path_factory.mktemp("rec"))


@pytest.mark.parametrize("fault_type", FAULT_TYPES)
def test_each_fault_type_recoverable_on_stripe(
    catalogs: dict[str, FaultCatalog], tmp_path: Path, fault_type: FaultType
) -> None:
    _check_recoverable(catalogs["stripe"], fault_type, 11, tmp_path)


def test_same_seed_same_fault(catalogs: dict[str, FaultCatalog], tmp_path: Path) -> None:
    cat = catalogs["stripe"]
    spec = IncidentSpec("x", "stripe", "t", 77, "null_spike")
    a, _, fa = inject_only(cat, tmp_path / "a", spec, _all_nodes(cat))
    b, _, fb = inject_only(cat, tmp_path / "b", spec, _all_nodes(cat))
    assert fa == fb
    assert tree_hash(a) == tree_hash(b)


def test_code_fault_text_changes_once(catalogs: dict[str, FaultCatalog], tmp_path: Path) -> None:
    cat = catalogs["jaffle_shop"]
    ws, _clean, applied = inject_only(
        cat,
        tmp_path / "w",
        IncidentSpec("x", "jaffle_shop", "t", 3, "model_logic_bug"),
        _all_nodes(cat),
    )
    assert applied and applied.location
    before = (cat.project_dir / applied.location.file).read_text()
    after = (ws / applied.location.file).read_text()
    assert before != after
    assert before.lower().count(applied.params["before"].lower()) - after.lower().count(
        applied.params["before"].lower()
    ) in (1, 0)  # count may be unchanged if `after` contains `before` (count -> count(distinct)


def test_operators_skip_jinja(catalogs: dict[str, FaultCatalog]) -> None:
    from faultline.inject.faults import _matches

    text = "select {{ sum(1) }} {# sum( #} -- sum(\n sum(x) from t"
    assert len(_matches(text, r"\bsum\s*\(")) == 1
