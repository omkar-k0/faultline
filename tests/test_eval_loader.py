"""Loader tests: integrity of the archive, and what a method may see."""

from __future__ import annotations

import io
import json
import re
import tarfile
from pathlib import Path

import pytest

from faultline.eval.loader import (
    BenchmarkError,
    Incident,
    clean_history,
    ensure_archive,
    extract,
    load_incidents,
    split_section,
)
from tests.conftest import ROOT

BENCHMARK = ROOT / "benchmark"

GIT_LOG = """bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb inject: sum_to_avg in model.p.orders

M\tmodels/orders.sql
cccccccccccccccccccccccccccccccccccccccc inject: null_spike in seed.p.raw

M\tseeds/raw.csv
aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa clean project

A\tdbt_project.yml
A\tmodels/orders.sql
A\tseeds/raw.csv
"""

LEAK = re.compile(r"inject:|faultline-injector|clean project|sum_to_avg|null_spike in")


def test_clean_history_drops_seed_commits_and_messages() -> None:
    history = clean_history(GIT_LOG)
    assert [c.message for c in history] == ["commit 1", "commit 2"]
    assert [c.hash[0] for c in history] == ["a", "b"]
    assert history[1].files == ("models/orders.sql",)
    assert not any(LEAK.search(c.message) for c in history)


def test_package_model_paths_count_as_models() -> None:
    log = "d" * 40 + " inject: x\n\nM\tpackages/stripe/models/stg_x.sql\n"
    assert len(clean_history(log)) == 1


def test_only_train_and_dev_can_be_evaluated() -> None:
    with pytest.raises(BenchmarkError, match="cannot be evaluated"):
        split_section(BENCHMARK, "anything_else")


def test_hash_mismatch_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.tar.gz").write_bytes(b"not the archive")
    section = {"archive": "x.tar.gz", "archive_sha256": "sha256:" + "0" * 64}
    with pytest.raises(BenchmarkError, match="manifest says"):
        ensure_archive(section, tmp_path, download=False)


def test_missing_archive_without_download(tmp_path: Path) -> None:
    section = {"archive": "nope.tar.gz", "archive_sha256": "sha256:" + "0" * 64}
    with pytest.raises(BenchmarkError, match="missing"):
        ensure_archive(section, tmp_path, download=False)


def test_unsafe_archive_member_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        data = b"x"
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(BenchmarkError, match="unsafe"):
        extract(archive, tmp_path / "out", "sha256:" + "1" * 64)
    assert not (tmp_path / "escape.txt").exists()


@pytest.fixture(scope="module")
def dev() -> list[Incident]:
    incidents, _ = load_incidents(
        "dev", benchmark_dir=BENCHMARK, dist_dir=ROOT / "dist", runs_dir=ROOT / "build/eval"
    )
    return incidents


def test_dev_loads_every_manifest_incident(dev: list[Incident]) -> None:
    manifest = json.loads((BENCHMARK / "manifest.json").read_text())
    assert [i.incident_id for i in dev] == sorted(
        e["id"] for e in manifest["splits"]["dev"]["incidents"]
    )


def test_methods_never_see_ground_truth(dev: list[Incident]) -> None:
    for incident in dev:
        assert not (incident.run_dir / "truth.json").exists()
        assert not hasattr(incident, "truth")


def test_no_injector_leaks_in_what_methods_see(dev: list[Incident]) -> None:
    for incident in dev:
        for commit in incident.history:
            assert not LEAK.search(commit.message)
        for commit in incident.history[1:]:  # after the clean snapshot, no seed-data commits
            assert not any(f.startswith("seeds/") for f in commit.files)
        assert "inject:" not in incident.dbt_log
        assert "faultline-injector" not in incident.dbt_log
