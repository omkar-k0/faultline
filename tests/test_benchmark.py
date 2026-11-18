from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from faultline.inject.benchmark import _archive, build_specs, load_plan, partition, split_nodes
from faultline.inject.catalog import FaultCatalog, build_catalog
from faultline.inject.faults import FAULT_TYPES
from tests.conftest import PROJECTS, ROOT

PLAN = ROOT / "benchmark" / "plan.toml"


@pytest.fixture(scope="module")
def catalogs() -> dict[str, FaultCatalog]:
    return {p: build_catalog(PROJECTS / p) for p in ("jaffle_shop", "stripe", "court_cases")}


def test_partition_is_disjoint_complete_and_proportional() -> None:
    nodes = [f"n{i}" for i in range(30)]
    out = partition("p", nodes, {"train": 2, "dev": 1})
    assert out["train"] | out["dev"] == set(nodes)
    assert not out["train"] & out["dev"]
    assert (len(out["train"]), len(out["dev"])) == (20, 10)
    assert partition("p", nodes, {"train": 2, "dev": 1}) == out


def test_partition_gives_small_split_a_node_first() -> None:
    assert partition("p", ["a"], {"train": 2, "dev": 1}) == {"train": set(), "dev": {"a"}}


def test_plan_splits_are_disjoint_per_project(catalogs: dict[str, FaultCatalog]) -> None:
    plan = load_plan(PLAN)
    for cat in catalogs.values():
        alloc = split_nodes(plan, cat)
        names = sorted(alloc)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                assert not alloc[a] & alloc[b], (cat.project, a, b)


def test_specs_cover_every_fault_type(catalogs: dict[str, FaultCatalog]) -> None:
    plan = load_plan(PLAN)
    for split in plan.splits.values():
        allowed = {p: split_nodes(plan, catalogs[p])[split.name] for p in split.projects}
        specs = build_specs(split, catalogs, allowed)
        types = [s.fault_type for s, _ in specs]
        for ft in FAULT_TYPES:
            assert types.count(ft) == split.incidents_per_fault
        assert types.count(None) == split.clean_runs_per_project * len(split.projects)
        assert len({s.incident_id for s, _ in specs}) == len(specs)
        assert len({s.seed for s, _ in specs}) == len(specs)
        assert all(s.seed > split.seed_base for s, _ in specs)


def test_seed_bases_must_differ(tmp_path: Path) -> None:
    plan = tmp_path / "plan.toml"
    plan.write_text(
        "[splits.a]\nprojects=['x']\nseed_base=1\nincidents_per_fault=1\nclean_runs_per_project=0\n"
        "[splits.b]\nprojects=['x']\nseed_base=1\nincidents_per_fault=1\nclean_runs_per_project=0\n"
    )
    with pytest.raises(ValueError, match="seed_base"):
        load_plan(plan)


def test_archive_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "split"
    (src / "inc_b").mkdir(parents=True)
    (src / "inc_a").mkdir()
    (src / "inc_b" / "x.json").write_text("{}")
    (src / "inc_a" / "y.json").write_text("[]")
    h1 = _archive(src, tmp_path / "one.tar.gz")
    h2 = _archive(src, tmp_path / "two.tar.gz")
    assert h1 == h2
    with tarfile.open(tmp_path / "one.tar.gz") as tar:
        assert tar.getnames() == ["split/inc_a/y.json", "split/inc_b/x.json"]
        assert all(m.mtime == 0 for m in tar.getmembers())
