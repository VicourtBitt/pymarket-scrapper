import hashlib
import json
import logging
from collections.abc import Iterator
from typing import Any, Callable, Dict, Optional

from sqlalchemy import create_engine, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import sessionmaker
from models import (
    ExtractionRun,
    ExtractionRunRequest,
    ExtractionSearch,
    ProductObservation,
    ProductRecord,
    VendorRecord,
)
from models.database import new_id, utc_now

IdentityResolver = Callable[[Dict[str, Any]], Optional[str]]
logger = logging.getLogger("pymarket_scrapper.pipeline.db_sink")


RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_FAILED = "failed"

_OBSERVED_FIELDS = ("title", "url", "price", "currency", "vendor_id", "metadata")


def observation_hash(product_data: Dict[str, Any]) -> str:
    """Stable hash of the observed product fields (identical rows share it)."""
    payload = {field: product_data.get(field) for field in _OBSERVED_FIELDS}
    encoded = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class PostgreSQLSink:
    """Persist vendors and products with PostgreSQL upserts.

    Optionally tracks an extraction run: between ``start_search`` and
    ``finish_search`` every loaded product also records an immutable
    ``ProductObservation`` in the same transaction as its upsert.
    """

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
        self.run_id: Optional[str] = None
        self.search_id: Optional[str] = None
        self._search_position = 0
        self.rows_loaded = 0
        self.rows_failed = 0

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
        # A run that could not resolve the vendor (search-only mode, a failed
        # vendor page) must not erase a vendor link stored by an earlier run.
        update_dict["vendor_id"] = func.coalesce(
            stmt.excluded.vendor_id, ProductRecord.__table__.c.vendor_id
        )
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=['product_id'],
            set_=update_dict
        )

        with self.SessionLocal() as session:
            try:
                session.execute(upsert_stmt)
                if self.search_id is not None:
                    session.execute(self._observation_statement(product_data))
                session.commit()
            except Exception:
                session.rollback()
                self.rows_failed += 1
                logger.exception("Unable to persist product %s", product_data.get("product_id"))
                raise
        self.rows_loaded += 1

    def _observation_statement(self, product_data: Dict[str, Any]) -> Any:
        self._search_position += 1
        return insert(ProductObservation).values(
            observation_id=new_id(),
            search_id=self.search_id,
            product_id=product_data["product_id"],
            observed_at=utc_now(),
            title=product_data.get("title"),
            url=product_data.get("url"),
            price=product_data.get("price"),
            currency=product_data.get("currency"),
            vendor_id=product_data.get("vendor_id"),
            position=self._search_position,
            raw_payload=json.loads(json.dumps(product_data, default=str)),
            row_hash=observation_hash(product_data),
        ).on_conflict_do_nothing(constraint="uq_observation_search_product_hash")

    # ------------------------------------------------------------ run lifecycle
    def _execute(self, statement: Any, description: str) -> None:
        with self.SessionLocal() as session:
            try:
                session.execute(statement)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("Unable to %s", description)
                raise

    def start_run(self, request: ExtractionRunRequest) -> str:
        """Create a ``running`` extraction run and reset the sink counters."""
        if request.marketplace != self.marketplace:
            raise ValueError(
                f"run marketplace {request.marketplace!r} does not match sink "
                f"marketplace {self.marketplace!r}"
            )
        run_id = new_id()
        self._execute(
            insert(ExtractionRun).values(
                run_id=run_id,
                marketplace=self.marketplace,
                status=RUN_RUNNING,
                started_at=utc_now(),
                config_hash=request.config_hash,
                requested_by=request.requested_by,
                source=request.source,
                rows_extracted=0,
                rows_loaded=0,
                rows_failed=0,
                metadata_blob=request.metadata,
            ),
            "start extraction run",
        )
        self.run_id = run_id
        self.rows_loaded = 0
        self.rows_failed = 0
        return run_id

    def start_search(
        self,
        search_term: str,
        sort_strategy: Optional[str] = None,
        requested_limit: Optional[int] = None,
    ) -> str:
        """Open a search within the current run; products are observed until
        ``finish_search``."""
        if self.run_id is None:
            raise RuntimeError("start_run must be called before start_search")
        search_id = new_id()
        self._execute(
            insert(ExtractionSearch).values(
                search_id=search_id,
                run_id=self.run_id,
                search_term=search_term,
                sort_strategy=sort_strategy,
                requested_limit=requested_limit,
                rows_extracted=0,
                status=RUN_RUNNING,
                started_at=utc_now(),
            ),
            "start extraction search",
        )
        self.search_id = search_id
        self._search_position = 0
        return search_id

    def finish_search(self, status: str, rows_extracted: int = 0) -> None:
        """Close the open search; later products are no longer observed."""
        if self.search_id is None:
            return
        search_id, self.search_id = self.search_id, None
        self._execute(
            update(ExtractionSearch)
            .where(ExtractionSearch.search_id == search_id)
            .values(status=status, rows_extracted=rows_extracted, finished_at=utc_now()),
            "finish extraction search",
        )

    def finish_run(
        self,
        status: str,
        rows_extracted: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Close the current run with its final counters."""
        if self.run_id is None:
            return
        if self.search_id is not None:
            self.finish_search(status)
        run_id, self.run_id = self.run_id, None
        self._execute(
            update(ExtractionRun)
            .where(ExtractionRun.run_id == run_id)
            .values(
                status=status,
                finished_at=utc_now(),
                rows_extracted=rows_extracted,
                rows_loaded=self.rows_loaded,
                rows_failed=self.rows_failed,
                error_message=(error_message or None) and error_message[:4000],
            ),
            "finish extraction run",
        )

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