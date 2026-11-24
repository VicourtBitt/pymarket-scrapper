"""SQLAlchemy persistence models.

These classes are deliberately separate from the Pydantic extraction contracts.
The identifiers are strings (rather than PostgreSQL UUID objects) because the
existing sink and ProductItem API already use strings and this keeps offline
SQLite tests and PostgreSQL migrations consistent.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp for ORM defaults."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    """Create a string identifier compatible with the existing application API."""
    return str(uuid4())


class Base(DeclarativeBase):
    """Declarative registry for production migrations and schema inspection."""


class VendorRecord(Base):
    __tablename__ = "vendors"

    vendor_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(2048))
    extracted_phones: Mapped[List[Any]] = mapped_column(JSON, default=list, nullable=False)
    extracted_emails: Mapped[List[Any]] = mapped_column(JSON, default=list, nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    cnpj: Mapped[Optional[str]] = mapped_column(String(32))
    storefront_url: Mapped[Optional[str]] = mapped_column(String(2048))
    metadata_blob: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    products: Mapped[List["ProductRecord"]] = relationship(back_populates="vendor")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    marketplace: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    config_hash: Mapped[Optional[str]] = mapped_column(String(128))
    requested_by: Mapped[Optional[str]] = mapped_column(String(255))
    source: Mapped[Optional[str]] = mapped_column(String(255))
    rows_extracted: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_loaded: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_failed: Mapped[int] = mapped_column(default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(String(4000))
    metadata_blob: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    searches: Mapped[List["ExtractionSearch"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ExtractionSearch(Base):
    __tablename__ = "extraction_searches"

    search_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    search_term: Mapped[str] = mapped_column(String(500), nullable=False)
    sort_strategy: Mapped[Optional[str]] = mapped_column(String(100))
    requested_limit: Mapped[Optional[int]] = mapped_column()
    rows_extracted: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    run: Mapped[ExtractionRun] = relationship(back_populates="searches")
    observations: Mapped[List["ProductObservation"]] = relationship(
        back_populates="search", cascade="all, delete-orphan"
    )


class ProductRecord(Base):
    """Canonical product table, retaining the legacy ``product_id`` API."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("marketplace", "external_product_id", name="uq_products_marketplace_external_id"),
        Index("ix_products_marketplace_title", "marketplace", "title"),
        Index("ix_products_vendor_id", "vendor_id"),
    )

    product_id: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    # Marketplace identity is supplied by the sink; there is no safe default.
    marketplace: Mapped[str] = mapped_column(String(100), nullable=False)
    external_product_id: Mapped[Optional[str]] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(2048))
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    currency: Mapped[Optional[str]] = mapped_column(String(12))
    vendor_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vendors.vendor_id", ondelete="SET NULL")
    )
    metadata_blob: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    vendor: Mapped[Optional[VendorRecord]] = relationship(back_populates="products")
    observations: Mapped[List["ProductObservation"]] = relationship(back_populates="product")


class ProductObservation(Base):
    __tablename__ = "product_observations"
    __table_args__ = (
        UniqueConstraint("search_id", "product_id", "row_hash", name="uq_observation_search_product_hash"),
        Index("ix_observations_product_observed_at", "product_id", "observed_at"),
        Index("ix_observations_search_position", "search_id", "position"),
    )

    observation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    search_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_searches.search_id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(1000))
    url: Mapped[Optional[str]] = mapped_column(String(2048))
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    currency: Mapped[Optional[str]] = mapped_column(String(12))
    vendor_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("vendors.vendor_id", ondelete="SET NULL")
    )
    position: Mapped[Optional[int]] = mapped_column()
    raw_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    row_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    search: Mapped[ExtractionSearch] = relationship(back_populates="observations")
    product: Mapped[ProductRecord] = relationship(back_populates="observations")
    vendor: Mapped[Optional[VendorRecord]] = relationship()
