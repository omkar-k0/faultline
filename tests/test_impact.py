from __future__ import annotations

import itertools

import networkx as nx
import pytest

from faultline.collectors.dbt_artifacts import Project
from faultline.lineage.column import ColumnRef, ProjectLineage, build_column_graph
from faultline.lineage.impact import TargetError, impact, resolve_target
from faultline.lineage.table import build_table_graph

J = "model.jaffle_shop."


def test_table_graph_edges(jaffle: Project) -> None:
    graph = build_table_graph(jaffle)
    assert graph.has_edge("seed.jaffle_shop.raw_payments", J + "stg_payments")
    assert graph.has_edge(J + "stg_payments", J + "customers")
    assert nx.is_directed_acyclic_graph(graph)


def test_node_downstream(jaffle: Project, jaffle_lineage: ProjectLineage) -> None:
    result = impact(jaffle, jaffle_lineage, "raw_payments")
    hits = {h.target: h for h in result.hits}
    assert set(hits) == {J + "stg_payments", J + "customers", J + "orders"}
    assert hits[J + "customers"].distance == 2
    assert hits[J + "customers"].path == (
        "seed.jaffle_shop.raw_payments",
        J + "stg_payments",
        J + "customers",
    )
    assert any("not_null_orders_amount" in t for t in result.tests)


def test_node_upstream(jaffle: Project, jaffle_lineage: ProjectLineage) -> None:
    result = impact(jaffle, jaffle_lineage, "customers", "upstream")
    assert {h.target for h in result.hits} == {
        J + "stg_customers",
        J + "stg_orders",
        J + "stg_payments",
        "seed.jaffle_shop.raw_customers",
        "seed.jaffle_shop.raw_orders",
        "seed.jaffle_shop.raw_payments",
    }
    assert all(J + "customers" in jaffle.nodes[t].depends_on for t in result.tests)


def test_column_downstream(jaffle: Project, jaffle_lineage: ProjectLineage) -> None:
    result = impact(jaffle, jaffle_lineage, "stg_payments.amount")
    assert {h.target for h in result.hits} == {
        J + "customers.customer_lifetime_value",
        J + "orders.amount",
        *(
            J + f"orders.{m}_amount"
            for m in ("credit_card", "coupon", "bank_transfer", "gift_card")
        ),
    }
    assert "test.jaffle_shop.not_null_orders_amount.106140f9fd" in result.tests


def test_column_upstream_reaches_seed(jaffle: Project, jaffle_lineage: ProjectLineage) -> None:
    result = impact(jaffle, jaffle_lineage, "customers.customer_lifetime_value", "upstream")
    assert [h.target for h in result.hits] == [
        J + "stg_payments.amount",
        "seed.jaffle_shop.raw_payments.amount",
    ]


def test_seed_column_has_no_upstream(jaffle: Project, jaffle_lineage: ProjectLineage) -> None:
    result = impact(jaffle, jaffle_lineage, "raw_payments.amount", "upstream")
    assert result.hits == ()


@pytest.mark.parametrize("fixture", ["jaffle", "stripe"])
def test_every_impact_path_exists_in_graph(fixture: str, request: pytest.FixtureRequest) -> None:
    project: Project = request.getfixturevalue(fixture)
    lineage: ProjectLineage = request.getfixturevalue(f"{fixture}_lineage")
    graph = build_column_graph(lineage)
    by_name = {str(n): n for n in graph.nodes}
    starts = [ref for ref in lineage.columns][:: max(1, len(lineage.columns) // 40)]
    for start in starts:
        for direction in ("downstream", "upstream"):
            result = impact(project, lineage, str(start), direction)
            for hit in result.hits:
                nodes = [by_name[p] for p in hit.path]
                pairs = itertools.pairwise(nodes)
                for a, b in pairs:
                    assert (
                        graph.has_edge(a, b) if direction == "downstream" else graph.has_edge(b, a)
                    )


def test_every_node_answers(jaffle: Project, jaffle_lineage: ProjectLineage) -> None:
    for uid, node in jaffle.nodes.items():
        if node.resource_type != "test":
            impact(jaffle, jaffle_lineage, uid)
            impact(jaffle, jaffle_lineage, uid, "upstream")


def test_unknown_names(jaffle: Project, jaffle_lineage: ProjectLineage) -> None:
    with pytest.raises(TargetError, match="no node"):
        resolve_target(jaffle, jaffle_lineage, "nope")
    with pytest.raises(TargetError, match="has no column"):
        resolve_target(jaffle, jaffle_lineage, "customers.nope")


def test_case_insensitive_column(jaffle: Project, jaffle_lineage: ProjectLineage) -> None:
    assert resolve_target(jaffle, jaffle_lineage, "CUSTOMERS.Customer_ID") == ColumnRef(
        J + "customers", "customer_id"
    )


def test_ambiguous_name() -> None:
    from faultline.lineage.column import build_column_lineage
    from tests.conftest import model, project, table

    proj = project(table("orders", ["id"]), model("orders", "select 1 as id", [], ["id"]))
    with pytest.raises(TargetError, match="ambiguous"):
        resolve_target(proj, build_column_lineage(proj), "orders")
    assert resolve_target(proj, build_column_lineage(proj), "model.p.orders") == "model.p.orders"
