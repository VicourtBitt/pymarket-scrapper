import logging
from collections.abc import Iterator
from typing import Any, Callable, Dict, Optional

from sqlalchemy import create_engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker
from models import VendorRecord, ProductRecord

IdentityResolver = Callable[[Dict[str, Any]], Optional[str]]
logger = logging.getLogger("pymarket_scrapper.pipeline.db_sink")


class PostgreSQLSink:
    """Persist vendors and products with PostgreSQL upserts."""

    def __init__(
        self,
        connection_url: str,
        identity_resolver: Optional[IdentityResolver] = None,
        *,
        marketplace: str,
    ) -> None:
        """
        Initialize the sink for one explicit marketplace.

        ``marketplace`` is deliberately required.  A missing marketplace must
        fail at construction time rather than turning a production row into an
        ambiguous ``unknown`` row.
        """
        if not marketplace or not marketplace.strip():
            raise ValueError("marketplace must be a non-empty string")
        self.marketplace = marketplace.strip()
        self.engine = create_engine(connection_url, echo=False, pool_size=5, max_overflow=10)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.identity_resolver = identity_resolver

    def close(self) -> None:
        """Release pooled database connections."""
        self.engine.dispose()

    def load_vendor(self, vendor_data: Dict[str, Any]) -> None:
        """
        Resolve an optional ERP identity and upsert one vendor.

        Args:
            vendor_data: Vendor fields including the required ``vendor_id``
                and ``name`` keys, plus optional ``cnpj`` and metadata fields.

        Raises:
            Exception: Propagates database failures after rolling back.
        """
        # 1. Execute Identity Resolution
        if self.identity_resolver:
            try:
                resolved_id = self.identity_resolver(vendor_data)
                # Ensure complex dicts are stringified (e.g. composite keys)
                if isinstance(resolved_id, dict):
                    import json
                    resolved_id = json.dumps(resolved_id)
                vendor_data = {**vendor_data, "external_id": resolved_id}
            except Exception:
                logger.exception(
                    "Identity resolution failed for vendor %s",
                    vendor_data.get("name"),
                )
                vendor_data = {**vendor_data, "external_id": None}

        # 2. Build the UPSERT statement (Insert on Conflict Do Update)
        stmt = insert(VendorRecord).values(
            vendor_id=vendor_data['vendor_id'],
            name=vendor_data['name'],
            url=vendor_data.get("url"),
            extracted_emails=vendor_data.get('extracted_emails', []),
            extracted_phones=vendor_data.get('extracted_phones', []),
            external_id=vendor_data.get('external_id'),
            cnpj=vendor_data.get('cnpj'),
            storefront_url=vendor_data.get('storefront_url'),
            metadata_blob=vendor_data.get('metadata', {})
        )

        # Update all fields EXCEPT the primary key if the vendor already exists
        update_dict = {c.name: c for c in stmt.excluded if not c.primary_key}
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=['vendor_id'],
            set_=update_dict
        )

        # 3. Execute and Commit
        with self.SessionLocal() as session:
            try:
                session.execute(upsert_stmt)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Unable to persist vendor %s", vendor_data.get("vendor_id"))
                raise

    def load_product(self, product_data: Dict[str, Any]) -> None:
        """
        Upsert one product in the configured marketplace.

        Args:
            product_data: Product fields including ``product_id``, ``title``,
                and ``vendor_id``.

        Raises:
            Exception: Propagates database failures after rolling back.
        """
        stmt = insert(ProductRecord).values(
            product_id=product_data['product_id'],
            marketplace=self.marketplace,
            external_product_id=product_data.get('external_id'),
            title=product_data['title'],
            url=product_data.get("url"),
            price=product_data.get('price'),
            currency=product_data.get('currency'),
            vendor_id=product_data['vendor_id'],
            metadata_blob=product_data.get('metadata', {})
        )

        update_dict = {c.name: c for c in stmt.excluded if c.name != "product_id"}
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=['product_id'],
            set_=update_dict
        )

        with self.SessionLocal() as session:
            try:
                session.execute(upsert_stmt)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Unable to persist product %s", product_data.get("product_id"))
                raise

    def iter_products_without_vendor(
        self, *, batch_size: int = 100
    ) -> Iterator[Dict[str, Optional[str]]]:
        """Yield product identifiers and URLs whose vendor is still unknown.

        Rows are fetched in bounded batches so a large backfill does not load
        the products table into memory.  The yielded dictionaries are safe to
        consume after the session is closed.
        """
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        last_product_id: Optional[str] = None
        while True:
            with self.SessionLocal() as session:
                filters = [
                    ProductRecord.marketplace == self.marketplace,
                    ProductRecord.vendor_id.is_(None),
                ]
                if last_product_id is not None:
                    filters.append(ProductRecord.product_id > last_product_id)
                rows = session.execute(
                    select(ProductRecord.product_id, ProductRecord.url)
                    .where(*filters)
                    .order_by(ProductRecord.product_id)
                    .limit(batch_size)
                ).all()
            if not rows:
                return
            for product_id, url in rows:
                yield {"product_id": product_id, "url": url}
            last_product_id = str(rows[-1][0])

    def update_product_vendor(self, product_id: str, vendor_id: str) -> None:
        """Set a product's vendor, rolling back and logging on database errors."""
        if not product_id or not vendor_id:
            raise ValueError("product_id and vendor_id are required")
        with self.SessionLocal() as session:
            try:
                session.execute(
                    update(ProductRecord)
                    .where(ProductRecord.product_id == product_id)
                    .values(vendor_id=vendor_id)
                )
                session.commit()
            except Exception:
                session.rollback()
                logger.exception(
                    "Unable to update vendor %s for product %s", vendor_id, product_id
                )
                raise