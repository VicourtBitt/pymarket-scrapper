"""Offline contract tests for the first persistence schema increment."""

from datetime import timezone
from decimal import Decimal
from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from sqlalchemy import Numeric

from models import (
    Base,
    ExtractionRun,
    ExtractionSearch,
    ProductObservation,
    ProductRecord,
)
from models.database import utc_now


def test_schema_has_expected_tables_and_relationships() -> None:
    assert {
        "vendors",
        "products",
        "extraction_runs",
        "extraction_searches",
        "product_observations",
    } <= set(Base.metadata.tables)
    assert ExtractionSearch.run.property.back_populates == "searches"
    assert ProductObservation.product.property.back_populates == "observations"


def test_product_identity_and_observation_constraints_are_explicit() -> None:
    products = ProductRecord.__table__
    observations = ProductObservation.__table__
    assert {"marketplace", "external_product_id"} <= set(products.c.keys())
    assert any(
        constraint.name == "uq_products_marketplace_external_id"
        for constraint in products.constraints
    )
    assert any(
        constraint.name == "uq_observation_search_product_hash"
        for constraint in observations.constraints
    )
    assert isinstance(products.c.price.type, Numeric)
    assert isinstance(observations.c.price.type, Numeric)


def test_timestamp_defaults_are_callable_and_utc_aware() -> None:
    run_default = ExtractionRun.__table__.c.started_at.default
    observation_default = ProductObservation.__table__.c.observed_at.default
    assert run_default is not None and run_default.is_callable
    assert observation_default is not None and observation_default.is_callable
    assert run_default.arg(None).tzinfo == timezone.utc
    assert observation_default.arg(None).tzinfo == timezone.utc


def test_json_defaults_are_not_shared_mutable_objects() -> None:
    products = ProductRecord.__table__
    first = products.c.metadata_blob.default.arg(None)
    second = products.c.metadata_blob.default.arg(None)
    assert first == second == {}
    assert first is not second


def test_foreign_keys_have_explicit_ondelete_actions() -> None:
    searches = ExtractionSearch.__table__
    observations = ProductObservation.__table__
    assert searches.c.run_id.foreign_keys.pop().ondelete == "CASCADE"
    assert observations.c.product_id.foreign_keys.pop().ondelete == "CASCADE"
    assert observations.c.search_id.foreign_keys.pop().ondelete == "CASCADE"
    assert observations.c.vendor_id.foreign_keys.pop().ondelete == "SET NULL"


def test_numeric_columns_preserve_decimal_contract() -> None:
    product_price = ProductRecord.__table__.c.price.type
    observation_price = ProductObservation.__table__.c.price.type
    assert (product_price.precision, product_price.scale) == (18, 4)
    assert (observation_price.precision, observation_price.scale) == (18, 4)
    assert isinstance(Decimal("12.3400"), Decimal)


def test_observation_is_removed_with_its_search_in_offline_sqlite() -> None:
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        run = ExtractionRun(marketplace="amazon", status="running")
        search = ExtractionSearch(run=run, search_term="seeds", status="running")
        product = ProductRecord(
            product_id="p-1",
            marketplace="amazon",
            title="Seeds",
            price=Decimal("12.3400"),
        )
        observation = ProductObservation(
            search=search,
            product=product,
            row_hash="hash-1",
            price=Decimal("12.3400"),
        )
        session.add(observation)
        session.commit()
        session.delete(run)
        session.commit()
        assert session.query(ProductObservation).count() == 0
        assert session.query(ProductRecord).count() == 1


def test_migration_does_not_reintroduce_removed_database_defaults() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0001_extraction_persistence.py"
    ).read_text()
    assert "server_default" not in migration
    assert 'sa.Column("marketplace", sa.String(100), nullable=False)' in migration
