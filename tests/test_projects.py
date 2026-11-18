"""Every vendored dbt project must carry its licence and a source note."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECTS = Path(__file__).resolve().parents[1] / "projects"
PROJECT_DIRS = sorted(p for p in PROJECTS.iterdir() if p.is_dir())


def test_at_least_one_project() -> None:
    assert PROJECT_DIRS


@pytest.mark.parametrize("project", PROJECT_DIRS, ids=lambda p: p.name)
def test_project_has_licence_and_source(project: Path) -> None:
    assert (project / "LICENCE").is_file()
    source = (project / "SOURCE.md").read_text()
    for field in ("Origin:", "Commit:", "Licence:"):
        assert field in source


@pytest.mark.parametrize("project", PROJECT_DIRS, ids=lambda p: p.name)
def test_project_is_a_dbt_project(project: Path) -> None:
    assert (project / "dbt_project.yml").is_file()
    assert (project / "profiles.yml").is_file()
