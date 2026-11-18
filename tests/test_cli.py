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


def test_lineage_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["lineage", "--project", "jaffle_shop"]) == 0
    assert "27 columns, 27 resolved" in capsys.readouterr().out


def test_impact_command_json(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    assert main(["impact", "stg_payments.amount", "--project", "jaffle_shop", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["level"] == "column"
    assert len(result["hits"]) == 6


def test_impact_unknown_target_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["impact", "nope", "--project", "jaffle_shop"]) == 2
    assert "no node named 'nope'" in capsys.readouterr().err


def test_handcheck_command(tmp_path: object, capsys: pytest.CaptureFixture[str]) -> None:
    from pathlib import Path

    out = Path(str(tmp_path)) / "sheet"
    args = [
        "lineage",
        "handcheck",
        "--project",
        "jaffle_shop",
        "--project",
        "stripe",
        "--out",
        str(out),
    ]
    assert main(args) == 0
    assert out.with_suffix(".csv").read_text().count("\n") == 31
    assert out.with_suffix(".md").is_file()
