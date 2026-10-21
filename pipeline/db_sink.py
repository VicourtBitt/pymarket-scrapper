import logging
from typing import Callable, Dict, Any, Optional
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker
from models import VendorRecord, ProductRecord

IdentityResolver = Callable[[Dict[str, Any]], Optional[str]]
logger = logging.getLogger("pymarket_scrapper.pipeline.db_sink")

class PostgreSQLSink:
    def __init__(
        self, connection_url: str, identity_resolver: IdentityResolver = None
    ) -> None:
        """
        Initializes the connection to the DB and creates tables if they don't exist.
        """
        self.engine = create_engine(connection_url, echo=False, pool_size=5, max_overflow=10)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.identity_resolver = identity_resolver

    def close(self) -> None:
        """Release pooled database connections."""
        self.engine.dispose()

    def load_vendor(self, vendor_data: Dict[str, Any]) -> None:
        """
        Executes the identity callback (if provided) and performs an UPSERT on the vendor.
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
            url=str(vendor_data.get('url', '')),
            extracted_emails=vendor_data.get('extracted_emails', []),
            extracted_phones=vendor_data.get('extracted_phones', []),
            external_id=vendor_data.get('external_id'),
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

    def load_product(self, product_data: dict) -> None:
        """
        Performs an UPSERT on the product record.
        """
        stmt = insert(ProductRecord).values(
            product_id=product_data['product_id'],
            title=product_data['title'],
            url=str(product_data['url']),
            price=product_data.get('price'),
            vendor_id=product_data['vendor_id'],
            metadata_blob=product_data.get('metadata', {})
        )

        update_dict = {c.name: c for c in stmt.excluded if not c.primary_key}
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