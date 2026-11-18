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
from faultline.lineage.column import ProjectLineage, build_column_lineage
from faultline.lineage.handcheck import build_sheet, to_csv, to_markdown
from faultline.lineage.impact import Direction, TargetError, impact

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
    except (ArtifactError, TargetError) as exc:
        print(f"faultline: {exc}", file=sys.stderr)
        return 2
    return code


if __name__ == "__main__":
    raise SystemExit(main())
