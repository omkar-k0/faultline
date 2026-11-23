"""M7: exact rebuilds, the fix drafter, draft PRs, and the test generator."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb
import pytest

from faultline.fixes.draft import draft, root_package
from faultline.fixes.evaluate import FixOutcome, try_fix
from faultline.fixes.evaluate import summarise as fix_summary
from faultline.fixes.pr import open_draft_pr, write_draft
from faultline.inject.rebuild import RebuildMismatch, load_truth_doc, rebuild
from faultline.testgen.evaluate import summarise as tg_summary
from faultline.testgen.generate import learn, relation_ref, to_dbt_tests
from tests.conftest import ROOT, model, project, table

RAW, STG = "seed.p.raw_orders", "model.p.stg_orders"
STG_SQL = (
    "with src as (\n    select * from {{ ref('raw_orders') }}\n)\nselect id, amount from src\n"
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny dbt repo with one seed and one staging model, under git."""
    r = tmp_path / "repo"
    (r / "models").mkdir(parents=True)
    (r / "dbt_project.yml").write_text("name: 'p'\nversion: '1.0'\n")
    (r / "models" / "stg_orders.sql").write_text(STG_SQL)
    _git(r, "init", "-q")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "create")
    return r


PROJECT = project(
    table("raw_orders", ["id", "amount"]),
    model("stg_orders", STG_SQL, [RAW], ["id", "amount"]),
)


def _cause(
    kind: str,
    node: str,
    column: str | None = None,
    commit: str | None = None,
    explains: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "node": node,
        "column": column,
        "commit": commit,
        "description": f"{kind} at {node}",
        "explains": explains or [],
    }


# --- the fix drafter ------------------------------------------------------------


def test_root_package_is_read_from_dbt_project(repo: Path) -> None:
    assert root_package(repo) == "p"


def test_revert_puts_the_model_back(repo: Path) -> None:
    path = repo / "models" / "stg_orders.sql"
    path.write_text(STG_SQL.replace("amount", "amount * 100 as amount"))
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "change")
    commit = _git(repo, "rev-parse", "HEAD")
    fix = draft(repo, PROJECT, _cause("code_change", STG, commit=commit), {})
    assert fix.pattern == "revert_commit" and fix.files == {"models/stg_orders.sql": STG_SQL}
    assert "-select id, amount * 100 as amount from src" in fix.diff(repo)


def test_dedupe_wraps_every_model_reading_the_source(repo: Path) -> None:
    fix = draft(repo, PROJECT, _cause("duplicate_rows", RAW, "id"), {})
    assert fix.pattern == "dedupe_rows"
    sql = fix.files["models/stg_orders.sql"]
    assert sql.startswith("-- faultline fix:") and sql.rstrip().endswith(
        "select distinct * from faultline_input"
    )
    con = duckdb.connect()
    con.sql(
        "create table raw_orders as select * from (values (1, 5), (1, 5), (2, 7)) t(id, amount)"
    )
    rendered = sql.replace("{{ ref('raw_orders') }}", "raw_orders").split("\n", 1)[1]
    assert sorted(con.sql(rendered).fetchall()) == [(1, 5), (2, 7)]


def test_renamed_column_is_mapped_back(repo: Path) -> None:
    missing = {"source": "schema", "node": RAW, "column": "amount", "observed": "missing"}
    new = {"source": "schema", "node": RAW, "column": "amount_new", "observed": "new"}
    cause = _cause("source_column", RAW, "amount", explains=[missing])
    fix = draft(repo, PROJECT, cause, {"symptoms": [missing, new]})
    assert fix.pattern == "map_renamed_column"
    assert (
        '(select *, "amount_new" as "amount" from {{ ref(\'raw_orders\') }})'
        in (fix.files["models/stg_orders.sql"])
    )


def test_dropped_column_and_changed_values_get_no_fix(repo: Path) -> None:
    missing = {"source": "schema", "node": RAW, "column": "amount", "observed": "missing"}
    dropped = draft(
        repo,
        PROJECT,
        _cause("source_column", RAW, "amount", explains=[missing]),
        {"symptoms": [missing]},
    )
    nulls = draft(repo, PROJECT, _cause("source_column", RAW, "amount"), {})
    assert not dropped.proposed and "dropped at the source" in dropped.reason
    assert not nulls.proposed and "fix is at the source" in nulls.reason


# --- draft PRs ------------------------------------------------------------------


def test_write_draft_changes_nothing_in_the_repo(repo: Path, tmp_path: Path) -> None:
    fix = draft(repo, PROJECT, _cause("duplicate_rows", RAW, "id"), {})
    files = write_draft(repo, "run1", fix, tmp_path / "out")
    assert [f.name for f in files] == ["run1.patch", "run1.md"]
    assert (repo / "models" / "stg_orders.sql").read_text() == STG_SQL
    assert "never merges" in files[1].read_text()


def test_open_pr_is_a_draft_and_never_merges(repo: Path) -> None:
    calls: list[list[str]] = []

    def fake(cmd: Sequence[str], cwd: Path) -> str:
        calls.append(list(cmd))
        return "https://github.com/x/y/pull/1\n" if cmd[0] == "gh" else ""

    fix = draft(repo, PROJECT, _cause("duplicate_rows", RAW, "id"), {})
    assert open_draft_pr(repo, "run1", fix, runner=fake) == "https://github.com/x/y/pull/1"
    gh = [c for c in calls if c[0] == "gh"]
    assert len(gh) == 1 and gh[0][:4] == ["gh", "pr", "create", "--draft"]
    # No command merges: no `git merge`, no `gh pr merge`, no auto-merge flag.
    assert not any("merge" in c[:3] or "--auto" in c for c in calls)
    nothing = draft(repo, PROJECT, _cause("source_column", RAW, "amount"), {})
    with pytest.raises(ValueError, match="no fix to open"):
        open_draft_pr(repo, "run2", nothing, runner=fake)


# --- exact rebuilds -------------------------------------------------------------


def test_rebuild_matches_the_recorded_inputs(tmp_path: Path) -> None:
    truth = load_truth_doc(ROOT / "benchmark", "dev", "inc_jaffle_shop_dev_014")
    built = rebuild(truth, tmp_path / "ws", ROOT / "projects", ROOT / "benchmark/plan.toml")
    assert built.fault_commit == truth["location"]["commit"]
    tampered = {**truth, "hashes": {"inputs": "sha256:" + "0" * 64}}
    with pytest.raises(RebuildMismatch):
        rebuild(tampered, tmp_path / "ws2", ROOT / "projects", ROOT / "benchmark/plan.toml")


def test_heldout_is_never_rebuilt() -> None:
    with pytest.raises(ValueError, match="never rebuilt"):
        load_truth_doc(ROOT / "benchmark", "heldout", "x")
    with pytest.raises(ValueError, match="never rebuilt"):
        rebuild(
            {"incident_id": "x", "project": "jira", "split": "heldout", "seed": 1, "fault": None},
            Path(tempfile.mkdtemp()) / "ws",
        )


def test_a_drafted_fix_restores_the_run() -> None:
    """End to end on one dev run: triage's cause, the drafted fix, two dbt builds."""
    from faultline.eval.loader import load_incidents
    from faultline.eval.run import harness_references
    from faultline.eval.score import load_truth
    from faultline.monitors.core import MonitorConfig
    from faultline.triage.method import triage_incident

    bdir = ROOT / "benchmark"
    incidents, _ = load_incidents("dev", bdir, ROOT / "dist", ROOT / "build/eval")
    truths = {i.incident_id: load_truth(bdir, "dev", i.incident_id) for i in incidents}
    refs = harness_references(incidents, truths)
    run = next(i for i in incidents if i.incident_id == "inc_jaffle_shop_dev_005")
    report = triage_incident(run, refs[run.incident_id], MonitorConfig()).report()
    out = try_fix(
        load_truth_doc(bdir, "dev", run.incident_id),
        str(run.run_dir),
        report,
        str(ROOT / "projects"),
    )
    assert out.pattern == "dedupe_rows" and out.build_ok and out.fixed and not out.still_off


def test_fix_rate_counts_runs_without_a_fix() -> None:
    rows = [
        FixOutcome("a", "duplicate_keys", "c", "dedupe_rows", "r", True, True, (), True),
        FixOutcome("b", "null_spike", "c", "none", "r", False),
        FixOutcome("c", "clean", None, "none", "r", False),
    ]
    m = fix_summary(rows)
    assert m["faulted"]["fixed"] == {"count": 1, "n": 2, "rate": 0.5}
    assert m["faulted"]["fixed_when_proposed"]["rate"] == 1.0
    assert m["clean"]["false_fixes"]["count"] == 0


# --- the test generator ---------------------------------------------------------


def _prof(rows: int, amount_max: float, nulls: int = 0) -> dict[str, Any]:
    return {
        RAW: {
            "rows": rows,
            "columns": {
                "id": {
                    "type": "INTEGER",
                    "non_null": rows,
                    "distinct": rows,
                    "min": 1.0,
                    "max": float(rows),
                    "mean": (rows + 1) / 2,
                    "median": (rows + 1) / 2,
                },
                "amount": {
                    "type": "INTEGER",
                    "non_null": rows - nulls,
                    "distinct": 9,
                    "min": 0.0,
                    "max": amount_max,
                    "mean": 5.0,
                    "median": 5.0,
                },
                "status": {"type": "VARCHAR", "non_null": rows, "distinct": 4},
            },
        },
    }


def test_learn_keeps_only_what_held_in_every_clean_run() -> None:
    checks = {c.name: c for c in learn(PROJECT, [_prof(100, 10.0), _prof(102, 12.0, nulls=3)])[RAW]}
    assert set(checks) == {
        "rows",
        "not_null:id",
        "unique:id",
        "range:id",
        "null_share:amount",
        "not_null:status",
        "range:amount",
        "mean:id",
        "mean:amount",
        "distinct:status",
    }
    assert "not between 98 and 104" in checks["rows"].condition
    assert "> 0.07941" in checks["null_share:amount"].condition


def test_generated_tests_are_warn_only_dbt_singular_tests() -> None:
    files = to_dbt_tests(PROJECT, learn(PROJECT, [_prof(100, 10.0), _prof(101, 11.0)]))
    ((path, sql),) = files.items()
    assert path == "tests/faultline_generated/faultline_gen_s_raw_orders.sql"
    assert "severity='warn'" in sql and "{{ ref('raw_orders') }}" in sql and "__REL__" not in sql
    src = table("charge", ["id"], resource_type="source")
    src = type(src)(**{**src.__dict__, "unique_id": "source.stripe.stripe.charge"})
    assert relation_ref(project(src), "source.stripe.stripe.charge") == (
        "{{ source('stripe', 'charge') }}"
    )


def test_generated_checks_catch_a_fault_and_pass_clean_data() -> None:
    checks = learn(PROJECT, [_prof(4, 10.0), _prof(4, 10.0)])[RAW]
    con = duckdb.connect()

    def failed(rows: list[tuple[int, int | None, str]]) -> set[str]:
        con.execute("create or replace table r(id int, amount int, status varchar)")
        con.executemany("insert into r values (?, ?, ?)", rows)
        return {
            c.name
            for c in checks
            if con.execute(f"select {c.condition.replace('__REL__', 'r')}").fetchone()[0]
        }

    clean = [(1, 3, "a"), (2, 5, "b"), (3, 10, "c"), (4, 0, "d")]
    assert failed(clean) == set()
    assert failed([(1, 3, "a"), (1, 3, "a"), (3, 10, "c"), (4, 0, "d")]) == {"unique:id"}
    scaled = [(1, 3, "a"), (2, 500, "b"), (3, 10, "c"), (4, 0, "d")]
    assert failed(scaled) == {"range:amount", "mean:amount"}


def test_mutation_score_counts_generated_and_own_tests() -> None:
    rows = [
        {"fault_type": "null_spike", "generated_failed": ["t"], "own_failed": []},
        {"fault_type": "null_spike", "generated_failed": [], "own_failed": ["o"]},
        {"fault_type": "clean", "generated_failed": ["t2"], "own_failed": []},
        {"fault_type": "clean", "generated_failed": [], "own_failed": []},
    ]
    m = tg_summary([{**r, "incident_id": str(i)} for i, r in enumerate(rows)])
    assert m["faulted"]["generated"]["count"] == 1 and m["faulted"]["either"]["count"] == 2
    assert m["clean"]["false_alarm_runs"] == {"count": 1, "n": 2, "rate": 0.5}
    assert m["clean"]["failing_tests"] == ["t2"]
    assert json.dumps(m)
