from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from faultline.lineage.column import (
    ColumnRef,
    ProjectLineage,
    build_column_graph,
    build_column_lineage,
)
from tests.conftest import model, project, table

RAW = table("raw", ["id", "amount", "status", "user_id"])


def _up(lineage: ProjectLineage, model_name: str, column: str) -> set[tuple[str, str, str]]:
    entry = lineage.columns[ColumnRef(f"model.p.{model_name}", column)]
    return {(e.source.node.split(".")[-1], e.source.column, e.kind) for e in entry.upstream}


def _one(sql: str, columns: list[str], *extra: object) -> ProjectLineage:
    nodes = [RAW, *extra, model("m", sql, ["seed.p.raw"], columns)]
    return build_column_lineage(project(*nodes))  # type: ignore[arg-type]


def test_direct_and_renamed() -> None:
    lin = _one('select id, user_id as customer_id from "db"."main"."raw"', ["id", "customer_id"])
    assert _up(lin, "m", "id") == {("raw", "id", "direct")}
    assert _up(lin, "m", "customer_id") == {("raw", "user_id", "renamed")}


def test_rename_through_ctes() -> None:
    sql = """
        with a as (select id as order_id, amount from "db"."main"."raw"),
             b as (select order_id as oid, amount from a)
        select oid, amount from b
    """
    lin = _one(sql, ["oid", "amount"])
    assert _up(lin, "m", "oid") == {("raw", "id", "renamed")}
    assert _up(lin, "m", "amount") == {("raw", "amount", "direct")}


def test_derived_expressions() -> None:
    sql = """select amount / 100 as dollars,
                    case when status = 'x' then 1 else 0 end as flag,
                    cast(id as varchar) as id_text
             from "db"."main"."raw" """
    lin = _one(sql, ["dollars", "flag", "id_text"])
    assert _up(lin, "m", "dollars") == {("raw", "amount", "derived")}
    assert _up(lin, "m", "flag") == {("raw", "status", "derived")}
    assert _up(lin, "m", "id_text") == {("raw", "id", "derived")}


def test_aggregates() -> None:
    sql = """select user_id, sum(amount) as total, count(id) as n
             from "db"."main"."raw" group by user_id"""
    lin = _one(sql, ["user_id", "total", "n"])
    assert _up(lin, "m", "user_id") == {("raw", "user_id", "direct")}
    assert _up(lin, "m", "total") == {("raw", "amount", "aggregated")}
    assert _up(lin, "m", "n") == {("raw", "id", "aggregated")}


def test_window_function_is_derived() -> None:
    sql = """select id, row_number() over (partition by user_id order by amount) as rn
             from "db"."main"."raw" """
    lin = _one(sql, ["id", "rn"])
    assert _up(lin, "m", "rn") == {("raw", "user_id", "derived"), ("raw", "amount", "derived")}


def test_select_star_is_expanded() -> None:
    lin = _one('with s as (select * from "db"."main"."raw") select * from s', RAW.column_names())
    for col in RAW.column_names():
        assert _up(lin, "m", col) == {("raw", col, "direct")}


def test_join_takes_each_side() -> None:
    other = table("users", ["id", "name"])
    sql = """select r.id, u.name from "db"."main"."raw" r
             join "db"."main"."users" u on r.user_id = u.id"""
    nodes = [RAW, other, model("m", sql, ["seed.p.raw", "seed.p.users"], ["id", "name"])]
    lin = build_column_lineage(project(*nodes))
    assert _up(lin, "m", "id") == {("raw", "id", "direct")}
    assert _up(lin, "m", "name") == {("users", "name", "direct")}


def test_literal_column_is_constant() -> None:
    lin = _one(
        "select 'stripe' as source_relation, cast(null as int) as x", ["source_relation", "x"]
    )
    for col in ("source_relation", "x"):
        entry = lin.columns[ColumnRef("model.p.m", col)]
        assert entry.status == "constant"
        assert entry.upstream == ()


def test_unknown_table_is_unresolved_not_dropped() -> None:
    lin = _one('select id from "db"."main"."not_in_project"', ["id"])
    entry = lin.columns[ColumnRef("model.p.m", "id")]
    assert entry.status == "unresolved"
    assert entry.reason and "not in manifest" in entry.reason


def test_broken_sql_is_unresolved_with_reason() -> None:
    lin = _one("select from where", ["id"])
    entry = lin.columns[ColumnRef("model.p.m", "id")]
    assert entry.status == "unresolved"
    assert entry.reason and entry.reason.startswith("sqlglot:")


def test_ephemeral_model_is_a_lineage_hop() -> None:
    eph_sql = 'select id as eid, amount from "db"."main"."raw"'
    eph = model("e", eph_sql, ["seed.p.raw"], materialized="ephemeral")
    down_sql = """with __dbt__cte__e as (select id as eid, amount from "db"."main"."raw")
                  select eid, amount * 2 as double from __dbt__cte__e"""
    down = model("d", down_sql, ["model.p.e"], ["eid", "double"])
    lin = build_column_lineage(project(RAW, eph, down))
    assert lin.node_columns["model.p.e"] == ("eid", "amount")
    assert _up(lin, "e", "eid") == {("raw", "id", "renamed")}
    assert _up(lin, "d", "eid") == {("e", "eid", "direct")}
    assert _up(lin, "d", "double") == {("e", "amount", "derived")}


def test_incremental_self_reference_is_ignored() -> None:
    sql = """select id from "db"."main"."raw"
             where id > (select max(id) from "db"."main"."m")"""
    lin = _one(sql, ["id"])
    assert _up(lin, "m", "id") == {("raw", "id", "direct")}


# Golden lineage for jaffle_shop, written by hand from the model SQL.
JAFFLE_GOLDEN = {
    "customers.customer_id": {("stg_customers", "customer_id", "direct")},
    "customers.first_name": {("stg_customers", "first_name", "direct")},
    "customers.last_name": {("stg_customers", "last_name", "direct")},
    "customers.first_order": {("stg_orders", "order_date", "aggregated")},
    "customers.most_recent_order": {("stg_orders", "order_date", "aggregated")},
    "customers.number_of_orders": {("stg_orders", "order_id", "aggregated")},
    "customers.customer_lifetime_value": {("stg_payments", "amount", "aggregated")},
    "orders.order_id": {("stg_orders", "order_id", "direct")},
    "orders.customer_id": {("stg_orders", "customer_id", "direct")},
    "orders.order_date": {("stg_orders", "order_date", "direct")},
    "orders.status": {("stg_orders", "status", "direct")},
    "orders.amount": {("stg_payments", "amount", "aggregated")},
    **{
        f"orders.{m}_amount": {
            ("stg_payments", "amount", "aggregated"),
            ("stg_payments", "payment_method", "aggregated"),
        }
        for m in ("credit_card", "coupon", "bank_transfer", "gift_card")
    },
    "stg_customers.customer_id": {("raw_customers", "id", "renamed")},
    "stg_customers.first_name": {("raw_customers", "first_name", "direct")},
    "stg_customers.last_name": {("raw_customers", "last_name", "direct")},
    "stg_orders.order_id": {("raw_orders", "id", "renamed")},
    "stg_orders.customer_id": {("raw_orders", "user_id", "renamed")},
    "stg_orders.order_date": {("raw_orders", "order_date", "direct")},
    "stg_orders.status": {("raw_orders", "status", "direct")},
    "stg_payments.payment_id": {("raw_payments", "id", "renamed")},
    "stg_payments.order_id": {("raw_payments", "order_id", "direct")},
    "stg_payments.payment_method": {("raw_payments", "payment_method", "direct")},
    "stg_payments.amount": {("raw_payments", "amount", "derived")},
}


def test_jaffle_golden(jaffle_lineage: ProjectLineage) -> None:
    computed = {}
    for ref, entry in jaffle_lineage.columns.items():
        key = f"{ref.node.split('.')[-1]}.{ref.column}"
        computed[key] = {
            (e.source.node.split(".")[-1], e.source.column, e.kind) for e in entry.upstream
        }
    assert computed == JAFFLE_GOLDEN


@pytest.mark.parametrize("fixture", ["jaffle_lineage", "stripe_lineage"])
def test_every_model_column_has_one_entry(fixture: str, request: pytest.FixtureRequest) -> None:
    lineage: ProjectLineage = request.getfixturevalue(fixture)
    for node in lineage.project.models:
        cols = lineage.node_columns[node.unique_id]
        assert cols, node.unique_id
        for col in cols:
            assert ColumnRef(node.unique_id, col) in lineage.columns
    assert lineage.coverage()["unresolved"] == 0


@pytest.mark.parametrize("fixture", ["jaffle_lineage", "stripe_lineage"])
def test_edges_point_at_known_columns(fixture: str, request: pytest.FixtureRequest) -> None:
    lineage: ProjectLineage = request.getfixturevalue(fixture)
    for entry in lineage.columns.values():
        for edge in entry.upstream:
            assert edge.source.node in lineage.project.nodes
            assert edge.source.column in lineage.node_columns[edge.source.node], (entry, edge)


# Model -> source pairs where the compiled SQL reads a relation that dbt's
# depends_on does not list. Found in fivetran dbt_stripe at 7f5d6ae: the tmp
# models pick the table through variables, so the declared source differs.
UNDECLARED = {
    "jaffle_lineage": set(),
    "stripe_lineage": {
        ("model.stripe.stg_stripe__price_plan_tmp", "source.stripe.stripe.price"),
        ("model.stripe.stg_stripe__subscription_tmp", "source.stripe.stripe.subscription_history"),
    },
}


@pytest.mark.parametrize("fixture", sorted(UNDECLARED))
def test_undeclared_dependencies_are_reported(fixture: str, request: pytest.FixtureRequest) -> None:
    lineage: ProjectLineage = request.getfixturevalue(fixture)
    pairs = {(target.node, edge.source.node) for target, edge in lineage.undeclared_edges()}
    assert pairs == UNDECLARED[fixture]


def test_column_graph_is_acyclic(stripe_lineage: ProjectLineage) -> None:
    import networkx as nx

    assert nx.is_directed_acyclic_graph(build_column_graph(stripe_lineage))


# Property test: random chains of models, each column a copy, rename, expression
# or aggregate of a column in its parent. The lineage must recover every edge.
OPS = ("direct", "renamed", "derived", "aggregated")


@st.composite
def chains(
    draw: st.DrawFn,
) -> tuple[list[object], dict[tuple[str, str], set[tuple[str, str, str]]]]:
    n_cols = draw(st.integers(min_value=1, max_value=5))
    parent_cols = [f"c{i}" for i in range(n_cols)]
    nodes: list[object] = [table("t0", parent_cols)]
    parent_id, parent_name = "seed.p.t0", "t0"
    expected: dict[tuple[str, str], set[tuple[str, str, str]]] = {}
    for depth in range(1, draw(st.integers(min_value=1, max_value=4)) + 1):
        ops = draw(st.lists(st.sampled_from(OPS), min_size=1, max_size=5))
        aggregate = "aggregated" in ops
        select, cols, group = [], [], []
        for i, op in enumerate(ops):
            src = draw(st.sampled_from(parent_cols))
            if aggregate and op != "aggregated":
                op = "aggregated"
            out = src if op == "direct" else f"m{depth}_{i}"
            if out in cols:
                out = f"m{depth}_{i}"
                op = "renamed" if op == "direct" else op
            expr = {
                "direct": src,
                "renamed": f"{src} as {out}",
                "derived": f"{src} + 1 as {out}",
                "aggregated": f"sum({src}) as {out}",
            }[op]
            select.append(expr)
            cols.append(out)
            expected[(f"m{depth}", out)] = {(parent_name, src, op)}
        sql = f'select {", ".join(select)} from "db"."main"."{parent_name}"'
        if group:
            sql += " group by " + ", ".join(group)
        nodes.append(model(f"m{depth}", sql, [parent_id], cols))
        parent_id, parent_name, parent_cols = f"model.p.m{depth}", f"m{depth}", cols
    return nodes, expected


@settings(max_examples=60, deadline=None)
@given(chains())
def test_property_random_chains(
    case: tuple[list[object], dict[tuple[str, str], set[tuple[str, str, str]]]],
) -> None:
    nodes, expected = case
    lin = build_column_lineage(project(*nodes))  # type: ignore[arg-type]
    for (model_name, col), edges in expected.items():
        assert _up(lin, model_name, col) == edges
    assert lin.coverage()["total"] == len(expected)
