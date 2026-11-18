from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from heldout_guard import (  # noqa: E402
    AddedLine,
    FileChange,
    find_violations,
    main,
    parse_added_lines,
    parse_name_status,
)


def test_parse_name_status_handles_renames() -> None:
    out = "M\tsrc/a.py\nR100\tbenchmark/dev/x.json\tbenchmark/heldout/x.json\nD\tREADME.md\n"
    assert parse_name_status(out) == [
        FileChange("M", "src/a.py"),
        FileChange("R", "benchmark/heldout/x.json", "benchmark/dev/x.json"),
        FileChange("D", "README.md"),
    ]


@pytest.mark.parametrize("status", ["A", "M", "D"])
def test_any_change_under_heldout_fails(status: str) -> None:
    assert find_violations([FileChange(status, "benchmark/heldout/inc_001/truth.json")], [])


def test_rename_out_of_heldout_fails() -> None:
    change = FileChange("R", "benchmark/dev/inc.json", "benchmark/heldout/inc.json")
    assert find_violations([change], [])


def test_dev_and_train_changes_pass() -> None:
    changes = [FileChange("A", "benchmark/dev/a.json"), FileChange("M", "benchmark/train/b.json")]
    assert find_violations(changes, []) == []


@pytest.mark.parametrize(
    "text",
    [
        'SPLIT = "benchmark/heldout"',
        'Path("benchmark") / "heldout"',
        "HELD_OUT = 1",
        'split = "held-out"',
    ],
)
def test_src_reference_fails(text: str) -> None:
    assert find_violations([], [AddedLine("src/faultline/triage/rules.py", 3, text)])


def test_allowlisted_file_and_non_src_pass() -> None:
    added = [
        AddedLine("src/faultline/eval/splits.py", 1, 'HELDOUT = "benchmark/heldout"'),
        AddedLine("tests/test_x.py", 1, '"benchmark/heldout"'),
        AddedLine("README.md", 1, "heldout is scored once"),
    ]
    assert find_violations([], added) == []


def test_parse_added_lines_tracks_paths_and_numbers() -> None:
    diff = (
        "diff --git a/src/a.py b/src/a.py\n"
        "--- a/src/a.py\n"
        "+++ b/src/a.py\n"
        "@@ -0,0 +4,2 @@\n"
        "+x = 1\n"
        "+y = 'heldout'\n"
        "diff --git a/src/b.py b/src/b.py\n"
        "--- a/src/b.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-gone = 1\n"
    )
    assert parse_added_lines(diff) == [
        AddedLine("src/a.py", 4, "x = 1"),
        AddedLine("src/a.py", 5, "y = 'heldout'"),
    ]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _commit(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "change")


def test_main_end_to_end_clean(repo: Path) -> None:
    _commit(repo, "src/faultline/lineage/graph.py", "x = 1\n")
    assert main(["guard", "main"]) == 0


def test_main_end_to_end_heldout_file(repo: Path) -> None:
    _commit(repo, "benchmark/heldout/inc_1/truth.json", "{}\n")
    assert main(["guard", "main"]) == 1


def test_main_end_to_end_src_reference(repo: Path) -> None:
    _commit(repo, "src/faultline/triage/rules.py", 'p = "benchmark/heldout"\n')
    assert main(["guard", "main"]) == 1
