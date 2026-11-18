from __future__ import annotations

import importlib

import pytest

import faultline
from faultline.cli import main

SUBPACKAGES = [
    "collectors",
    "lineage",
    "monitors",
    "incidents",
    "triage",
    "fixes",
    "testgen",
    "llm",
    "mcp",
    "inject",
    "eval",
]


def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"faultline {faultline.__version__}"


def test_no_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: faultline" in capsys.readouterr().out


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_layout_subpackages_import(name: str) -> None:
    importlib.import_module(f"faultline.{name}")
