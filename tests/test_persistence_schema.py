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
    VendorRecord,
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


def test_vendor_cnpj_is_optional_and_sized_for_formatted_values() -> None:
    cnpj = VendorRecord.__table__.c.cnpj
    assert cnpj.nullable is True
    assert cnpj.type.length == 32


def test_vendor_storefront_url_is_optional_and_sized_for_urls() -> None:
    storefront_url = VendorRecord.__table__.c.storefront_url
    assert storefront_url.nullable is True
    assert storefront_url.type.length == 2048


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
    products = ProductRecord.__table__
    composite = {
        constraint.name: constraint
        for table in (products, observations)
        for constraint in table.foreign_key_constraints
        if constraint.name
    }
    assert searches.c.run_id.foreign_keys.pop().ondelete == "CASCADE"
    assert observations.c.search_id.foreign_keys.pop().ondelete == "CASCADE"
    assert composite["fk_observations_product"].ondelete == "CASCADE"
    # Composite vendor keys cannot SET NULL without nulling marketplace.
    assert composite["fk_products_vendor"].ondelete is None
    assert composite["fk_observations_vendor"].ondelete is None
    for name in ("fk_products_vendor", "fk_observations_product", "fk_observations_vendor"):
        assert composite[name].column_keys[0] == "marketplace"


def test_identities_are_scoped_to_the_marketplace() -> None:
    assert [c.name for c in ProductRecord.__table__.primary_key] == ["marketplace", "product_id"]
    assert [c.name for c in VendorRecord.__table__.primary_key] == ["marketplace", "vendor_id"]
    assert ProductObservation.__table__.c.marketplace.nullable is False


def _sqlite_session() -> Session:
    engine = create_engine("sqlite://")
    event.listen(engine, "connect", lambda dbapi_connection, _: dbapi_connection.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.create_all(engine)
    return Session(engine)


def test_same_ids_coexist_in_two_marketplaces_in_offline_sqlite() -> None:
    with _sqlite_session() as session:
        for marketplace in ("amazon_br", "amazon_us"):
            session.add(VendorRecord(marketplace=marketplace, vendor_id="S1", name=marketplace))
            session.add(ProductRecord(
                marketplace=marketplace, product_id="B000", title=marketplace, vendor_id="S1",
            ))
        session.commit()
        rows = session.query(ProductRecord.marketplace, ProductRecord.vendor_id).order_by(
            ProductRecord.marketplace
        ).all()
        assert rows == [("amazon_br", "S1"), ("amazon_us", "S1")]


def test_product_cannot_reference_another_marketplaces_vendor_in_offline_sqlite() -> None:
    import pytest
    from sqlalchemy.exc import IntegrityError

    with _sqlite_session() as session:
        session.add(VendorRecord(marketplace="amazon_br", vendor_id="S1", name="BR"))
        session.commit()
        session.add(ProductRecord(
            marketplace="amazon_us", product_id="B000", title="US", vendor_id="S1",
        ))
        with pytest.raises(IntegrityError):
            session.commit()


def test_marketplace_identity_migration_is_chained_and_guards_downgrade() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0004_marketplace_scoped_identity.py"
    ).read_text()
    assert 'revision: str = "0004_marketplace_scoped_identity"' in migration
    assert 'down_revision: Optional[str] = "0003_add_vendor_storefront_url"' in migration
    assert 'op.create_primary_key("products_pkey", "products", ["marketplace", "product_id"])' in migration
    assert 'op.create_primary_key("vendors_pkey", "vendors", ["marketplace", "vendor_id"])' in migration
    assert "Cannot downgrade" in migration


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


def test_vendor_cnpj_migration_is_chained_and_reversible() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0002_add_vendor_cnpj.py"
    )
    migration = migration_path.read_text()
    assert 'revision: str = "0002_add_vendor_cnpj"' in migration
    assert 'down_revision: Optional[str] = "0001_extraction_persistence"' in migration
    assert 'op.add_column("vendors"' in migration
    assert 'op.drop_column("vendors", "cnpj")' in migration


def test_vendor_storefront_url_migration_is_chained_and_reversible() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0003_add_vendor_storefront_url.py"
    )
    migration = migration_path.read_text()
    assert 'revision: str = "0003_add_vendor_storefront_url"' in migration
    assert 'down_revision: Optional[str] = "0002_add_vendor_cnpj"' in migration
    assert 'sa.Column("storefront_url", sa.String(2048), nullable=True)' in migration
    assert 'op.drop_column("vendors", "storefront_url")' in migration
