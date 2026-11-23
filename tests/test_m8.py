"""M8: the final-split rules, the MCP server, post-mortems, and triage on jira.

Nothing here opens benchmark/heldout/. The jira test uses only the vendored jira
project as built by `make setup`.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from faultline.eval.loader import BenchmarkError, split_section
from faultline.eval.splits import FINAL_SPLIT, ScoredAlready, check_final_scoring
from faultline.mcp.server import MCPConfig, build_server
from faultline.monitors.core import MonitorConfig, detect
from tests.conftest import ROOT

# --- the final split ------------------------------------------------------------


def test_final_split_only_through_eval(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkError):
        split_section(ROOT / "benchmark", FINAL_SPLIT)  # every other path is refused
    section = split_section(ROOT / "benchmark", FINAL_SPLIT, allow_final=True)
    assert section["archive"].endswith(".tar.gz")


def test_final_split_is_scored_once(tmp_path: Path) -> None:
    check_final_scoring(FINAL_SPLIT, tmp_path, "triage")  # nothing yet: fine
    (tmp_path / FINAL_SPLIT).mkdir()
    (tmp_path / FINAL_SPLIT / "triage.json").write_text("{}")
    with pytest.raises(ScoredAlready):
        check_final_scoring(FINAL_SPLIT, tmp_path, "triage")
    check_final_scoring("dev", tmp_path, "triage")  # other splits can be re-scored
    (tmp_path / FINAL_SPLIT / "triage_llm.json").write_text('{"incomplete": {}}')
    check_final_scoring(FINAL_SPLIT, tmp_path, "triage_llm")  # never was a result


# --- the MCP server -------------------------------------------------------------


def _call(server: Any, name: str, args: dict[str, Any]) -> Any:
    result = asyncio.run(server.call_tool(name, args))
    blocks = result.content if hasattr(result, "content") else result[0]
    return json.loads(blocks[0].text)


@pytest.fixture
def mcp_server(tmp_path: Path) -> Any:
    from faultline.incidents.store import IncidentStore

    store = IncidentStore(tmp_path / "f.duckdb")
    store.save(
        {
            "run": "r1",
            "incidents": [
                {
                    "incident": 1,
                    "status": "confirmed",
                    "symptoms": [{"x": 1}],
                    "causes": [{"description": "values of seed.p.raw.amount changed"}],
                },
            ],
        }
    )
    store.close()
    cfg = MCPConfig(ROOT / "projects/jaffle_shop", tmp_path / "f.duckdb", ROOT / "eval/results")
    return build_server(cfg)


def test_mcp_tools_are_all_read_only(mcp_server: Any) -> None:
    tools = asyncio.run(mcp_server.list_tools())
    assert {t.name for t in tools} == {
        "list_incidents",
        "get_report",
        "get_lineage",
        "impact_of",
        "get_results",
    }
    assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)


def test_mcp_reads_incidents_lineage_and_results(mcp_server: Any) -> None:
    assert _call(mcp_server, "list_incidents", {})["incident"] == "r1#1"
    assert _call(mcp_server, "get_report", {"incident": "r1#1"})["status"] == "confirmed"
    assert "error" in _call(mcp_server, "get_report", {"incident": "nope"})
    impact = _call(mcp_server, "impact_of", {"target": "stg_orders"})
    assert "model.jaffle_shop.orders" in impact["affected"]
    triage = _call(mcp_server, "get_results", {"split": "dev", "method": "triage"})
    assert triage["metrics"]["faulted"]["n"] == 48 and "incidents" not in triage


def test_mcp_results_cannot_leave_the_results_folder(mcp_server: Any) -> None:
    for split, method in [("..", "pyproject"), ("dev", "../../faultline"), ("dev", "nope")]:
        assert "error" in _call(mcp_server, "get_results", {"split": split, "method": method})


# --- post-mortems ---------------------------------------------------------------


def test_postmortem_says_not_confirmed_plainly() -> None:
    from faultline.collectors.dbt_artifacts import load_project
    from faultline.lineage.column import build_column_lineage
    from faultline.triage.postmortem import PostmortemInputs, render

    project = load_project(ROOT / "projects/jaffle_shop")
    report = {
        "run": "x",
        "detected": True,
        "incidents": [
            {
                "incident": 1,
                "status": "not_confirmed",
                "proposed": 4,
                "rejected": 4,
                "causes": [],
                "symptoms": [
                    {
                        "source": "volume",
                        "node": "model.jaffle_shop.orders",
                        "column": None,
                        "observed": "1",
                        "expected": "99..101",
                        "severity": 3,
                    }
                ],
            }
        ],
    }
    text = render(PostmortemInputs("x", report, project, build_column_lineage(project)))
    assert "Root cause not confirmed" in text and "Not assessed" in text
    assert "No fix drafted" in text and "Not checked" in text


# --- triage on jira, from the vendored project only -----------------------------


def test_triage_runs_on_the_jira_project() -> None:
    from faultline.collectors.dbt_artifacts import load_project
    from faultline.inject.run import profile_workspace
    from faultline.lineage.table import build_table_graph
    from faultline.triage.agent import Triage
    from faultline.triage.evidence import RunContext, column_lineage

    jira = ROOT / "projects/jira"
    project = load_project(jira)
    profile = profile_workspace(jira)
    seeds = sorted(n for n in profile if n.startswith("seed.") and profile[n].get("rows", 0) > 10)
    assert seeds, "jira seeds are profiled"
    broken = copy.deepcopy(profile)
    broken[seeds[0]]["rows"] = 1  # most rows gone at one seed
    _lineage, graph = column_lineage(project)
    ctx = RunContext(
        "jira-smoke",
        project,
        build_table_graph(project),
        graph,
        broken,
        [profile, profile, profile],
        (),
        frozenset(),
    )
    cfg = MonitorConfig()
    t = Triage(ctx, detect(broken, [profile] * 3, cfg), [], cfg).run()
    assert t.prediction().detected
    assert t.reports[0].ranked[0].hypothesis.node == seeds[0]
