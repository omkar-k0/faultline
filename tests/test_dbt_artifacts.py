from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from faultline.collectors.dbt_artifacts import ArtifactError, Project, load_project
from tests.conftest import PROJECTS


def test_jaffle_nodes(jaffle: Project) -> None:
    assert {n.name for n in jaffle.models} == {
        "stg_customers",
        "stg_orders",
        "stg_payments",
        "customers",
        "orders",
    }
    assert {n.name for n in jaffle.by_type("seed")} == {
        "raw_customers",
        "raw_orders",
        "raw_payments",
    }
    assert len(jaffle.tests) == 20
    assert jaffle.adapter_type == "duckdb"


def test_models_have_compiled_sql_and_catalog_columns(jaffle: Project) -> None:
    for node in jaffle.models:
        assert node.compiled_code and "{{" not in node.compiled_code
        assert node.columns, node.unique_id
    customers = jaffle.nodes["model.jaffle_shop.customers"]
    assert customers.column_names()[0] == "customer_id"
    assert customers.depends_on == (
        "model.jaffle_shop.stg_customers",
        "model.jaffle_shop.stg_orders",
        "model.jaffle_shop.stg_payments",
    )


def test_column_tests_are_attached(jaffle: Project) -> None:
    test = next(t for t in jaffle.tests if t.name == "unique_customers_customer_id")
    assert test.attached_node == "model.jaffle_shop.customers"
    assert test.test_column == "customer_id"


def test_stripe_has_ephemeral_models(stripe: Project) -> None:
    ephemeral = {n.name for n in stripe.models if n.is_ephemeral}
    assert ephemeral == {
        "int_stripe__deduped_subscription_item",
        "int_stripe__subscription_discount",
    }


@pytest.fixture
def copied(tmp_path: Path) -> Path:
    target = tmp_path / "proj" / "target"
    target.mkdir(parents=True)
    for name in ("manifest.json", "catalog.json"):
        shutil.copy(PROJECTS / "jaffle_shop" / "target" / name, target / name)
    return tmp_path / "proj"


def test_missing_catalog_fails_loudly(copied: Path) -> None:
    (copied / "target" / "catalog.json").unlink()
    with pytest.raises(ArtifactError, match=r"catalog\.json not found"):
        load_project(copied)


def test_unsupported_manifest_version(copied: Path) -> None:
    path = copied / "target" / "manifest.json"
    doc = json.loads(path.read_text())
    doc["metadata"]["dbt_schema_version"] = "https://schemas.getdbt.com/dbt/manifest/v99.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(ArtifactError, match="v99 not supported"):
        load_project(copied)


def test_invalid_json(copied: Path) -> None:
    (copied / "target" / "catalog.json").write_text("{not json")
    with pytest.raises(ArtifactError, match="invalid JSON"):
        load_project(copied)
