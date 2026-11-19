"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from faultline import __version__
from faultline.collectors.dbt_artifacts import ArtifactError, Project, load_project
from faultline.eval.loader import BenchmarkError
from faultline.lineage.column import ProjectLineage, build_column_lineage
from faultline.lineage.handcheck import build_sheet, to_csv, to_markdown
from faultline.lineage.impact import Direction, TargetError, impact
from faultline.llm.client import LLMError

PROJECTS_DIR = Path("projects")


def _project_dir(name: str) -> Path:
    path = Path(name)
    if (path / "dbt_project.yml").is_file():
        return path
    return PROJECTS_DIR / name


def _load(name: str) -> tuple[Project, ProjectLineage]:
    project = load_project(_project_dir(name))
    return project, build_column_lineage(project)


def _cmd_lineage(args: argparse.Namespace) -> int:
    if not args.project:
        print("faultline lineage: --project is required", file=sys.stderr)
        return 2
    for name in args.project:
        project, lineage = _load(name)
        counts = lineage.coverage()
        models = len(project.models)
        if args.json:
            undeclared = sorted({(t.node, e.source.node) for t, e in lineage.undeclared_edges()})
            doc = {
                "project": project.name,
                "models": models,
                "columns": counts,
                "undeclared_dependencies": [list(p) for p in undeclared],
            }
            print(json.dumps(doc))
            continue
        print(
            f"{project.name}: {models} models, {counts['total']} columns, "
            f"{counts['resolved']} resolved, {counts['constant']} constant, "
            f"{counts['unresolved']} unresolved"
        )
        for entry in sorted(lineage.columns.values(), key=lambda e: str(e.target)):
            if entry.status == "unresolved":
                print(f"  unresolved {entry.target}: {entry.reason}")
        undeclared = sorted({(t.node, e.source.node) for t, e in lineage.undeclared_edges()})
        for model_id, source_id in undeclared:
            print(f"  warning: {model_id} reads {source_id}, which is not in its depends_on")
    return 0


def _cmd_handcheck(args: argparse.Namespace) -> int:
    loaded = [_load(name) for name in args.project]
    rows = build_sheet([lin for _, lin in loaded], n=args.n, seed=args.seed)
    names = [p.name for p, _ in loaded]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".csv").write_text(to_csv(rows))
    out.with_suffix(".md").write_text(to_markdown(rows, seed=args.seed, projects=names))
    print(f"wrote {len(rows)} rows to {out.with_suffix('.md')} and {out.with_suffix('.csv')}")
    if len(rows) < args.n:
        print(f"warning: asked for {args.n} columns, only {len(rows)} available", file=sys.stderr)
        return 1
    return 0


def _cmd_impact(args: argparse.Namespace) -> int:
    project, lineage = _load(args.project)
    direction: Direction = "upstream" if args.upstream else "downstream"
    result = impact(project, lineage, args.target, direction)
    if args.json:
        print(json.dumps(asdict(result), indent=2))
        return 0
    print(f"{direction} of {result.start} ({result.level}): {len(result.hits)} affected")
    for hit in result.hits:
        print(f"  [{hit.distance}] {hit.target}  ({hit.resource_type})")
        print(f"      path: {' -> '.join(hit.path)}")
    if result.tests:
        print(f"tests on the affected {result.level}s: {len(result.tests)}")
        for test in result.tests:
            print(f"  {test}")
    return 0


def _cmd_inject(args: argparse.Namespace) -> int:
    from faultline.inject.catalog import build_catalog
    from faultline.inject.incident import IncidentSpec, generate

    project_dir = _project_dir(args.project)
    catalog = build_catalog(project_dir)
    nodes = {s.node for s in catalog.seeds} | {m.node for m in catalog.models}
    fault = None if args.fault == "none" else args.fault
    incident_id = f"inc_{catalog.project}_scratch_{args.seed}"
    out = Path(args.out) / incident_id
    spec = IncidentSpec(incident_id, catalog.project, "scratch", args.seed, fault)
    doc = generate(catalog, spec, nodes, out / "run", out / "truth.json")
    print(
        json.dumps({k: doc[k] for k in ("incident_id", "fault", "location", "observed")}, indent=2)
    )
    return 0


def _cmd_benchmark_generate(args: argparse.Namespace) -> int:
    from faultline.inject.benchmark import generate_split, load_plan

    plan = load_plan(Path(args.plan))
    if args.split not in plan.splits:
        print(f"faultline: split {args.split!r} is not in {args.plan}", file=sys.stderr)
        return 2

    def progress(done: int, total: int, incident_id: str) -> None:
        print(f"[{done}/{total}] {incident_id}", flush=True)

    section = generate_split(
        plan,
        args.split,
        projects_dir=PROJECTS_DIR,
        benchmark_dir=Path(args.benchmark_dir),
        runs_dir=Path(args.runs_dir),
        dist_dir=Path(args.dist_dir),
        workers=args.workers,
        progress=progress,
    )
    print(
        f"{args.split}: {len(section['incidents'])} incidents, {len(section['skipped'])} skipped, "
        f"archive {section['archive']} {section['archive_sha256']}"
    )
    return 0


def _cmd_benchmark_summary(args: argparse.Namespace) -> int:
    from faultline.inject.benchmark import summarise

    rows = summarise(Path(args.benchmark_dir), args.split)
    print(f"{'project:fault':45s} {'incidents':>9s} {'dbt_flagged':>11s}")
    for key, row in sorted(rows.items()):
        print(f"{key:45s} {row['incidents']:9d} {row['dbt_flagged']:11d}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from faultline.eval.run import run_eval
    from faultline.llm.client import OpenAICompatibleClient, load_config

    client = None
    if args.baseline == "raw_log_llm":
        client = OpenAICompatibleClient(load_config(Path(args.config)))
    command = f"faultline eval --split {args.split} --baseline {args.baseline}"
    doc = run_eval(
        args.split,
        args.baseline,
        results_dir=Path(args.results_dir),
        client=client,
        download=not args.no_download,
        command=command,
        config_path=Path(args.config),
    )
    m = doc["metrics"]
    f, c = m["faulted"], m["clean"]
    print(
        f"{args.baseline} on {args.split}: {f['n']} faulted, {c['n']} clean, "
        f"config {doc['config_hash']} -> {args.results_dir}/{args.split}/{args.baseline}.md"
    )
    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    from faultline.eval.loader import load_incidents
    from faultline.eval.run import harness_references
    from faultline.eval.score import load_truth
    from faultline.incidents.store import IncidentStore
    from faultline.monitors.core import load_monitor_config
    from faultline.triage.method import triage_incident
    from faultline.triage.report import render

    run_id = args.incident_id.split("#", 1)[0]
    benchmark_dir = Path(args.benchmark_dir)
    incidents, _ = load_incidents(args.split, benchmark_dir, download=not args.no_download)
    match = [i for i in incidents if i.incident_id == run_id]
    if not match:
        print(f"no run {run_id!r} in split {args.split}", file=sys.stderr)
        return 2
    truths = {
        i.incident_id: load_truth(benchmark_dir, args.split, i.incident_id) for i in incidents
    }
    references = harness_references(incidents, truths)[run_id]
    result = triage_incident(match[0], references, load_monitor_config(Path(args.config)))
    report = result.report()
    store = IncidentStore(Path(args.store))
    keys = store.save(report)
    store.close()
    print(json.dumps(report, indent=1) if args.json else render(report), end="")
    if keys and not args.json:
        print(f"\nStored as {', '.join(keys)} in {args.store}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="faultline",
        description="Reliability assistant for dbt Core projects.",
    )
    parser.add_argument("--version", action="version", version=f"faultline {__version__}")
    sub = parser.add_subparsers(dest="command")

    lin = sub.add_parser("lineage", help="column lineage coverage for a project")
    lin.add_argument("--project", action="append", help="name under projects/ or a path")
    lin.add_argument("--json", action="store_true")
    lin.set_defaults(func=_cmd_lineage)
    lin_sub = lin.add_subparsers(dest="lineage_command")
    hc = lin_sub.add_parser("handcheck", help="write a hand-check sheet of sampled columns")
    hc.add_argument("--project", action="append", required=True)
    hc.add_argument("--n", type=int, default=30)
    hc.add_argument("--seed", type=int, default=0)
    hc.add_argument("--out", default="docs/handcheck/lineage")
    hc.set_defaults(func=_cmd_handcheck)

    imp = sub.add_parser("impact", help="what depends on a node or column, or what feeds it")
    imp.add_argument("target", help="node name or id, optionally .column")
    imp.add_argument("--project", required=True)
    imp.add_argument("--upstream", action="store_true", help="show what feeds the target")
    imp.add_argument("--json", action="store_true")
    imp.set_defaults(func=_cmd_impact)

    from faultline.eval.baselines import BASELINES
    from faultline.eval.loader import EVALUABLE_SPLITS
    from faultline.inject.faults import FAULT_TYPES

    ev = sub.add_parser("eval", help="score a baseline on a benchmark split")
    ev.add_argument("--split", required=True, choices=sorted(EVALUABLE_SPLITS))
    ev.add_argument("--baseline", required=True, choices=list(BASELINES))
    ev.add_argument("--results-dir", default="eval/results")
    ev.add_argument("--config", default="faultline.toml")
    ev.add_argument("--no-download", action="store_true", help="use dist/ only, never download")
    ev.set_defaults(func=_cmd_eval)

    tri = sub.add_parser("triage", help="triage one benchmark run and store its incidents")
    tri.add_argument("incident_id", help="benchmark run id, e.g. inc_stripe_dev_013")
    tri.add_argument("--split", default="dev", choices=sorted(EVALUABLE_SPLITS))
    tri.add_argument("--benchmark-dir", default="benchmark")
    tri.add_argument("--config", default="faultline.toml")
    tri.add_argument("--store", default="build/faultline.duckdb")
    tri.add_argument("--json", action="store_true")
    tri.add_argument("--no-download", action="store_true", help="use dist/ only, never download")
    tri.set_defaults(func=_cmd_triage)

    inj = sub.add_parser("inject", help="inject one fault into a copy of a project and run it")
    inj.add_argument("--project", required=True)
    inj.add_argument("--fault", required=True, choices=[*FAULT_TYPES, "none"])
    inj.add_argument("--seed", type=int, required=True)
    inj.add_argument("--out", default="build/incidents")
    inj.set_defaults(func=_cmd_inject)

    bench = sub.add_parser("benchmark", help="generate or summarise a benchmark split")
    bench_sub = bench.add_subparsers(dest="benchmark_command", required=True)
    gen = bench_sub.add_parser("generate", help="generate one split from the plan")
    gen.add_argument("--plan", default="benchmark/plan.toml")
    gen.add_argument("--split", required=True)
    gen.add_argument("--benchmark-dir", default="benchmark")
    gen.add_argument("--runs-dir", default="build/benchmark")
    gen.add_argument("--dist-dir", default="dist")
    gen.add_argument("--workers", type=int, default=3)
    gen.set_defaults(func=_cmd_benchmark_generate)
    summ = bench_sub.add_parser("summary", help="counts per project and fault type")
    summ.add_argument("--split", required=True)
    summ.add_argument("--benchmark-dir", default="benchmark")
    summ.set_defaults(func=_cmd_benchmark_summary)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    try:
        code: int = func(args)
    except (ArtifactError, TargetError, FileExistsError, BenchmarkError, LLMError) as exc:
        print(f"faultline: {exc}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())
