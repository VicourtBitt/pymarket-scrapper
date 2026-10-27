"""Offline tests for the PostgreSQL sink's write contract."""

from decimal import Decimal
from typing import Any, List

import pytest
from sqlalchemy.dialects import postgresql

from pipeline.db_sink import PostgreSQLSink


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


def test_load_vendor_upsert_persists_cnpj_and_accepts_missing_cnpj() -> None:
    sink = PostgreSQLSink("sqlite:///offline-test.db", marketplace="amazon")
    statements: List[Any] = []
    sink.SessionLocal = lambda: RecordingSession(statements)  # type: ignore[method-assign]

    sink.load_vendor({"vendor_id": "vendor-1", "name": "Example", "cnpj": "62.246.912/0001-03"})
    sink.load_vendor({"vendor_id": "vendor-2", "name": "Legacy"})

    supplied = statements[0].compile(dialect=postgresql.dialect())
    legacy = statements[1].compile(dialect=postgresql.dialect())
    assert supplied.params["cnpj"] == "62.246.912/0001-03"
    assert legacy.params["cnpj"] is None
    assert 'cnpj = excluded.cnpj' in str(supplied)
