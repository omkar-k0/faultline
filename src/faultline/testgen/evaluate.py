"""Mutation score of the generated tests on a split.

1. Rebuild the train split's clean runs (same day as everything else, since stripe
   models build dates up to the day they run) and learn checks per project from
   their profiles. No faulted run is looked at.
2. Rebuild every run of the scored split, add the generated tests, run dbt.
3. A faulted run is caught ("the mutant is killed") when a generated test fails or
   errors. Next to it: whether the project's own tests caught it in the same run.
   On clean runs, any failing generated test is a false alarm.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from faultline.collectors.dbt_artifacts import load_project
from faultline.eval.run import FAULT_ORDER, _git_commit
from faultline.inject.rebuild import rebuild
from faultline.inject.run import run_dbt
from faultline.testgen.generate import learn, to_dbt_tests

LEARN_SPLIT = "train"
BAD = {"fail", "error", "warn"}


def _truths(benchmark_dir: Path, split: str) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted((benchmark_dir / split).glob("*/truth.json"))]


def build_clean(truth: dict[str, Any], projects_dir: str) -> tuple[str, dict[str, Any], str, str]:
    """Rebuild one clean train run; return its project, profile, manifest and catalog."""
    with tempfile.TemporaryDirectory() as tmp:
        built = rebuild(truth, Path(tmp) / "ws", Path(projects_dir))
        capture = run_dbt(built.workspace)
        manifest = (built.workspace / "target" / "manifest.json").read_text()
        catalog = (built.workspace / "target" / "catalog.json").read_text()
    return truth["project"], capture.profile, manifest, catalog


def run_with_tests(
    truth: dict[str, Any], tests: dict[str, str], projects_dir: str
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        built = rebuild(truth, Path(tmp) / "ws", Path(projects_dir))
        for path, sql in tests.items():
            target = built.workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(sql)
        capture = run_dbt(built.workspace)
        results = (capture.run_results or {}).get("results", [])
        failed_checks = _failed_checks(built.workspace, results)
    generated = sorted(
        r["unique_id"].split(".")[2]
        for r in results
        if r["unique_id"].startswith("test.")
        and ".faultline_gen_" in r["unique_id"]
        and r["status"] in BAD
    )
    own = sorted(
        r["unique_id"]
        for r in results
        if r["unique_id"].startswith("test.")
        and ".faultline_gen_" not in r["unique_id"]
        and r["status"] in {"fail", "error"}
    )
    ran = sum(1 for r in results if ".faultline_gen_" in r["unique_id"])
    fault = truth.get("fault") or {}
    return {
        "incident_id": truth["incident_id"],
        "fault_type": fault.get("type") or "clean",
        "generated_failed": generated,
        "generated_ran": ran,
        "own_failed": own,
        "failed_checks": failed_checks,
        "build_ok": capture.build_ok,
    }


def _failed_checks(ws: Path, results: Sequence[dict[str, Any]]) -> list[str]:
    """The names of the checks behind each failing generated test, from its compiled SQL."""
    import duckdb

    dbs = sorted((ws / "target").glob("*.duckdb"))
    names: list[str] = []
    if not dbs:
        return names
    con = duckdb.connect(str(dbs[0]), read_only=True)
    try:
        for r in results:
            uid = r["unique_id"]
            if ".faultline_gen_" not in uid or r["status"] not in {"warn", "fail"}:
                continue
            test = uid.split(".")[2]
            compiled = sorted((ws / "target" / "compiled").rglob(f"{test}.sql"))
            if not compiled:
                continue
            try:
                rows = con.execute(compiled[0].read_text()).fetchall()
            except duckdb.Error:
                continue
            names += [f"{test}:{row[0]}" for row in rows]
    finally:
        con.close()
    return sorted(names)


def _rate(count: int, n: int) -> dict[str, Any]:
    return {"count": count, "n": n, "rate": round(count / n, 4) if n else None}


def summarise(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    faulted = [r for r in rows if r["fault_type"] != "clean"]
    clean = [r for r in rows if r["fault_type"] == "clean"]

    def block(rs: Sequence[dict[str, Any]]) -> dict[str, Any]:
        gen = sum(bool(r["generated_failed"]) for r in rs)
        own = sum(bool(r["own_failed"]) for r in rs)
        either = sum(bool(r["generated_failed"] or r["own_failed"]) for r in rs)
        return {
            "n": len(rs),
            "generated": _rate(gen, len(rs)),
            "own": _rate(own, len(rs)),
            "either": _rate(either, len(rs)),
        }

    return {
        "faulted": block(faulted),
        "by_fault_type": {
            ft: block([r for r in faulted if r["fault_type"] == ft])
            for ft in FAULT_ORDER
            if any(r["fault_type"] == ft for r in faulted)
        },
        "clean": {
            "n": len(clean),
            "false_alarm_runs": _rate(sum(bool(r["generated_failed"]) for r in clean), len(clean)),
            "own_false_alarm_runs": _rate(sum(bool(r["own_failed"]) for r in clean), len(clean)),
            "failing_tests": sorted({t for r in clean for t in r["generated_failed"]}),
            "failing_checks": sorted({c for r in clean for c in r.get("failed_checks", [])}),
        },
    }


def _pct(m: dict[str, Any]) -> str:
    return "n/a" if m["rate"] is None else f"{m['rate'] * 100:.1f}% ({m['count']}/{m['n']})"


def to_markdown(doc: dict[str, Any]) -> str:
    m = doc["metrics"]
    lines = [
        f"# Generated tests on {doc['split']}: mutation score",
        "",
        f"Command `{doc['command']}`. Tests learned from {doc['learned_from']} clean "
        f"{LEARN_SPLIT} runs only: {doc['tests_per_project']}. A faulted run is caught when "
        "a generated test fails on it (real dbt test, rebuilt run).",
        "",
        "| Fault type | n | Generated tests | Project's own tests | Either |",
        "|---|---|---|---|---|",
    ]
    for ft, r in m["by_fault_type"].items():
        lines.append(
            f"| {ft} | {r['n']} | {_pct(r['generated'])} | {_pct(r['own'])} | {_pct(r['either'])} |"
        )
    f = m["faulted"]
    lines += [
        f"| **all faulted (mutation score)** | {f['n']} | {_pct(f['generated'])} | "
        f"{_pct(f['own'])} | {_pct(f['either'])} |",
        "",
        "False alarms: clean runs where a generated test failed "
        f"{_pct(m['clean']['false_alarm_runs'])}; "
        f"where the project's own tests failed {_pct(m['clean']['own_false_alarm_runs'])}.",
    ]
    if m["clean"]["failing_tests"]:
        lines.append(
            "Generated tests that failed on a clean run: "
            + ", ".join(f"`{t}`" for t in m["clean"]["failing_tests"])
            + "."
        )
    return "\n".join(lines) + "\n"


def evaluate(
    split: str,
    benchmark_dir: Path = Path("benchmark"),
    projects_dir: Path = Path("projects"),
    results_dir: Path = Path("eval/results"),
    workers: int = 2,
) -> dict[str, Any]:
    if split == LEARN_SPLIT:
        raise ValueError("tests are learned from train; score them on dev")
    scored = _truths(benchmark_dir, split)
    projects = sorted({t["project"] for t in scored})
    learn_from = [
        t
        for t in _truths(benchmark_dir, LEARN_SPLIT)
        if t["fault"] is None and t["project"] in projects
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        built = list(pool.map(build_clean, learn_from, [str(projects_dir)] * len(learn_from)))
    tests: dict[str, dict[str, str]] = {}
    counts = {}
    with tempfile.TemporaryDirectory() as tmp:
        for project in projects:
            profiles = [p for proj, p, _, _ in built if proj == project]
            manifest, catalog = next((m, c) for proj, _, m, c in built if proj == project)
            target = Path(tmp) / project / "target"
            target.mkdir(parents=True)
            (target / "manifest.json").write_text(manifest)
            (target / "catalog.json").write_text(catalog)
            proj = load_project(Path(tmp) / project)
            checks = learn(proj, profiles)
            tests[project] = to_dbt_tests(proj, checks)
            counts[project] = (
                f"{project} {len(tests[project])} tests, "
                f"{sum(len(c) for c in checks.values())} checks"
            )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(
            pool.map(
                run_with_tests,
                scored,
                [tests[t["project"]] for t in scored],
                [str(projects_dir)] * len(scored),
            )
        )
    rows.sort(key=lambda r: r["incident_id"])
    doc = {
        "split": split,
        "command": f"faultline testgen eval --split {split}",
        "learned_from": len(learn_from),
        "tests_per_project": "; ".join(counts[p] for p in projects),
        "metrics": summarise(rows),
        "incidents": rows,
        "tests": tests,
    }
    out = results_dir / split
    out.mkdir(parents=True, exist_ok=True)
    (out / "testgen.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    (out / "testgen.md").write_text(to_markdown(doc))
    (out / "testgen.run.json").write_text(
        json.dumps({"git_commit": _git_commit()}, indent=1) + "\n"
    )
    return doc
