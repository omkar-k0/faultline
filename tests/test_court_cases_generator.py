"""The synthetic court data is reproducible from its seed."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.conftest import PROJECTS

PROJECT = PROJECTS / "court_cases"


def test_generator_reproduces_committed_seeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location(
        "court_gen", PROJECT / "generator" / "generate.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path)
    module.main()
    committed = sorted(p.name for p in (PROJECT / "seeds").glob("*.csv"))
    assert sorted(p.name for p in tmp_path.glob("*.csv")) == committed
    for name in committed:
        assert (tmp_path / name).read_bytes() == (PROJECT / "seeds" / name).read_bytes(), name


def test_names_are_codes_not_people() -> None:
    lawyers = (PROJECT / "seeds" / "raw_lawyers.csv").read_text().splitlines()[1:]
    judges = (PROJECT / "seeds" / "raw_judges.csv").read_text().splitlines()[1:]
    assert all(",Advocate " in row for row in lawyers)
    assert all(",Presiding Officer " in row for row in judges)
