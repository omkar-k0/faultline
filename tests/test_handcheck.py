from __future__ import annotations

import csv
import io
from collections import Counter

from faultline.lineage.column import ProjectLineage
from faultline.lineage.handcheck import FIELDS, build_sheet, to_csv, to_markdown


def test_thirty_rows_split_across_projects(
    jaffle_lineage: ProjectLineage, stripe_lineage: ProjectLineage
) -> None:
    rows = build_sheet([jaffle_lineage, stripe_lineage], n=30, seed=0)
    assert len(rows) == 30
    assert Counter(r.project for r in rows) == {"jaffle_shop": 15, "stripe": 15}
    assert len({(r.project, r.model, r.column) for r in rows}) == 30
    assert [r.id for r in rows] == list(range(1, 31))


def test_sampling_is_seeded(jaffle_lineage: ProjectLineage, stripe_lineage: ProjectLineage) -> None:
    a = build_sheet([jaffle_lineage, stripe_lineage], n=30, seed=7)
    b = build_sheet([jaffle_lineage, stripe_lineage], n=30, seed=7)
    c = build_sheet([jaffle_lineage, stripe_lineage], n=30, seed=8)
    assert a == b
    assert a != c


def test_sample_covers_several_kinds(stripe_lineage: ProjectLineage) -> None:
    rows = build_sheet([stripe_lineage], n=15, seed=0)
    assert len({r.kind for r in rows}) >= 4


def test_small_project_gives_its_share_to_the_other(
    jaffle_lineage: ProjectLineage, stripe_lineage: ProjectLineage
) -> None:
    rows = build_sheet([jaffle_lineage, stripe_lineage], n=80, seed=0)
    counts = Counter(r.project for r in rows)
    assert counts["jaffle_shop"] == 27
    assert counts["stripe"] == 53


def test_outputs(jaffle_lineage: ProjectLineage) -> None:
    rows = build_sheet([jaffle_lineage], n=5, seed=0)
    parsed = list(csv.reader(io.StringIO(to_csv(rows))))
    assert tuple(parsed[0]) == FIELDS
    assert len(parsed) == 6
    assert all(row[-2:] == ["", ""] for row in parsed[1:])
    md = to_markdown(rows, seed=0, projects=["jaffle_shop"])
    assert md.count("\n| ") == 6
