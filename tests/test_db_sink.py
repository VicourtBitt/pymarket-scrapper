"""Offline tests for the PostgreSQL sink's write contract."""

from decimal import Decimal
from typing import Any, List

import pytest
from sqlalchemy.dialects import postgresql

from models import ExtractionRunRequest
from pipeline.db_sink import PostgreSQLSink, observation_hash


class RecordingSession:
    """Minimal session double; no PostgreSQL service is needed for SQL tests."""

    def __init__(self, statements: List[Any]) -> None:
        self.statements = statements

    def __enter__(self) -> "RecordingSession":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, statement: Any) -> None:
        self.statements.append(statement)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_sink_requires_explicit_marketplace() -> None:
    with pytest.raises(TypeError):
        PostgreSQLSink("sqlite://")


def test_load_product_keeps_marketplace_and_sql_null_url() -> None:
    # Engine construction is offline; the recording session prevents I/O.
    sink = PostgreSQLSink(
        "sqlite:///offline-test.db",
        marketplace="amazon",
    )
    statements: List[Any] = []
    sink.SessionLocal = lambda: RecordingSession(statements)  # type: ignore[method-assign]
    sink.load_product(
        {
            "product_id": "product-1",
            "title": "Seeds",
            "url": None,
            "price": Decimal("4.2000"),
            "currency": "USD",
            "vendor_id": None,
        }
    )

    compiled = statements[0].compile(dialect=postgresql.dialect())
    assert compiled.params["marketplace"] == "amazon"
    assert compiled.params["url"] is None
    assert compiled.params["price"] == Decimal("4.2000")


def test_load_vendor_upsert_persists_cnpj_storefront_and_accepts_missing_fields() -> None:
    sink = PostgreSQLSink("sqlite:///offline-test.db", marketplace="amazon")
    statements: List[Any] = []
    sink.SessionLocal = lambda: RecordingSession(statements)  # type: ignore[method-assign]

    sink.load_vendor(
        {
            "vendor_id": "vendor-1",
            "name": "Example",
            "cnpj": "62.246.912/0001-03",
            "storefront_url": "https://example.test/store",
        }
    )
    sink.load_vendor({"vendor_id": "vendor-2", "name": "Legacy"})

    supplied = statements[0].compile(dialect=postgresql.dialect())
    legacy = statements[1].compile(dialect=postgresql.dialect())
    assert supplied.params["cnpj"] == "62.246.912/0001-03"
    assert supplied.params["storefront_url"] == "https://example.test/store"
    assert legacy.params["cnpj"] is None
    assert legacy.params["storefront_url"] is None
    assert 'cnpj = excluded.cnpj' in str(supplied)
    assert 'storefront_url = excluded.storefront_url' in str(supplied)


def _recording_sink() -> tuple[PostgreSQLSink, List[Any]]:
    sink = PostgreSQLSink("sqlite:///offline-test.db", marketplace="amazon")
    statements: List[Any] = []
    sink.SessionLocal = lambda: RecordingSession(statements)  # type: ignore[method-assign]
    return sink, statements


def _compiled(statement: Any) -> Any:
    return statement.compile(dialect=postgresql.dialect())


PRODUCT = {
    "product_id": "p-1",
    "title": "Seeds",
    "url": "https://example.test/p-1",
    "price": 4.2,
    "currency": "BRL",
    "vendor_id": None,
    "metadata": {},
}


def test_products_are_observed_only_while_a_search_is_open() -> None:
    sink, statements = _recording_sink()

    sink.load_product(PRODUCT)
    assert len(statements) == 1

    run_id = sink.start_run(ExtractionRunRequest(marketplace="amazon", source="test"))
    search_id = sink.start_search("seeds", "relevance", 10)
    sink.load_product(PRODUCT)
    sink.load_product({**PRODUCT, "product_id": "p-2"})
    sink.finish_search("succeeded", rows_extracted=2)
    sink.load_product(PRODUCT)
    sink.finish_run("succeeded", rows_extracted=2)

    tables = [statement.table.name for statement in statements]
    assert tables == [
        "products",
        "extraction_runs",
        "extraction_searches",
        "products", "product_observations",
        "products", "product_observations",
        "extraction_searches",
        "products",
        "extraction_runs",
    ]
    first_observation = _compiled(statements[4]).params
    second_observation = _compiled(statements[6]).params
    assert first_observation["search_id"] == search_id
    assert (first_observation["position"], second_observation["position"]) == (1, 2)
    assert first_observation["row_hash"] == observation_hash(PRODUCT)
    assert "ON CONFLICT ON CONSTRAINT uq_observation_search_product_hash DO NOTHING" in str(
        _compiled(statements[4])
    )
    run_insert = _compiled(statements[1]).params
    assert run_insert["run_id"] == run_id and run_insert["status"] == "running"
    run_update = _compiled(statements[-1]).params
    assert run_update["status"] == "succeeded"
    assert run_update["rows_loaded"] == 3
    assert run_update["rows_failed"] == 0


def test_run_marketplace_must_match_sink() -> None:
    sink, _ = _recording_sink()
    with pytest.raises(ValueError):
        sink.start_run(ExtractionRunRequest(marketplace="mercado_libre"))


def test_search_requires_a_run() -> None:
    sink, _ = _recording_sink()
    with pytest.raises(RuntimeError):
        sink.start_search("seeds")


def test_observation_hash_ignores_identity_and_detects_changes() -> None:
    assert observation_hash(PRODUCT) == observation_hash({**PRODUCT, "product_id": "other"})
    assert observation_hash(PRODUCT) != observation_hash({**PRODUCT, "price": 5.0})
