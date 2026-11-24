"""Extraction orchestration built on ``Pipeline``.

One ``ExtractionWorkflow`` drives every CLI mode. Vendors are resolved through
a single ``VendorResolver`` so each vendor page is requested at most once per
run, whichever mode (search enrichment, vendor-only, or backfill) asks for it.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable
from urllib.parse import urljoin

from crawlers.base import BaseCrawler, BaseVendorCrawler
from models import ExtractionRunRequest, ProductItem
from models.config import ProductFilter
from pipeline.deduplicator import Deduplicator
from pipeline.engine import Pipeline, PipelineStats, Stage
from pipeline.normalization import merge_product_details, normalize_vendor


class ExtractionMode(str, Enum):
    """Supported extraction scopes."""

    PRODUCT = "product"
    VENDOR = "vendor"
    ALL = "all"


class WorkflowSink(Protocol):
    """The sink operations the workflow needs."""

    def load_product(self, product_data: dict[str, Any]) -> None: ...

    def load_vendor(self, vendor_data: dict[str, Any]) -> None: ...


@runtime_checkable
class RunTracker(Protocol):
    """Optional sink capability: record extraction runs and searches."""

    def start_run(self, request: ExtractionRunRequest) -> str: ...

    def start_search(
        self, search_term: str, sort_strategy: Optional[str] = None,
        requested_limit: Optional[int] = None,
    ) -> str: ...

    def finish_search(self, status: str, rows_extracted: int = 0) -> None: ...

    def finish_run(
        self, status: str, rows_extracted: int = 0, error_message: Optional[str] = None
    ) -> None: ...


@dataclass
class VendorStats:
    resolved: int = 0
    cache_hits: int = 0
    failures: int = 0


class VendorResolver:
    """Extract, normalize, persist and cache vendors, once per vendor ID.

    A vendor is cached only after extraction and persistence succeed, so a
    failed vendor page can be retried by a later product.
    """

    def __init__(
        self,
        vendor_crawler: BaseVendorCrawler,
        sink: WorkflowSink,
        logger: logging.Logger,
    ) -> None:
        self.vendor_crawler = vendor_crawler
        self.sink = sink
        self.logger = logger
        self.cache: dict[str, dict[str, Any]] = {}
        self.stats = VendorStats()

    async def resolve(self, vendor_id: Any, vendor_url: Any) -> Optional[dict[str, Any]]:
        """Return the normalized vendor, extracting it only on a cache miss.

        Raises:
            Exception: Crawler or sink failures propagate to the caller.
        """
        if not vendor_id:
            return None
        key = str(vendor_id)
        if key in self.cache:
            self.stats.cache_hits += 1
            self.logger.info("vendor cache hit vendor_id=%s", key)
            return self.cache[key]
        if not vendor_url:
            return None

        details = await self.vendor_crawler.extract_vendor_info(str(vendor_url))
        if not isinstance(details, dict):
            raise TypeError("vendor detail extraction did not return a mapping")
        vendor = normalize_vendor(key, str(vendor_url), details)
        self.sink.load_vendor(vendor)
        self.logger.info("vendor persistence completed vendor_id=%s", key)
        self.cache[key] = vendor
        self.stats.resolved += 1
        return vendor


class TitleFilter:
    """Cheap streaming title filter applied before any detail-page request."""

    def __init__(self, product_filter: ProductFilter) -> None:
        self.product_filter = product_filter

    async def process(self, stream: AsyncIterator[ProductItem]) -> AsyncIterator[ProductItem]:
        async for product in stream:
            if self.product_filter.matches(product.title):
                yield product


class ExtractionWorkflow:
    """Compose crawlers, stages and the sink for one extraction job."""

    def __init__(
        self,
        crawler: BaseCrawler,
        vendor_crawler: BaseVendorCrawler,
        sink: WorkflowSink,
        sql_filter: Stage,
        product_filter: Optional[ProductFilter] = None,
        logger: Optional[logging.Logger] = None,
        catalog_limit: int = 50,
        detail_crawler: Optional[BaseCrawler] = None,
    ) -> None:
        """
        Args:
            crawler: Product crawler whose page runs the search pagination.
            detail_crawler: Product crawler for detail pages. It must use a
                different Playwright page than ``crawler``: the search
                generator is suspended mid-page while details are fetched, so
                sharing one page would navigate the search results away.
                Defaults to ``crawler`` (only safe in product mode or tests).
        """
        self.crawler = crawler
        self.detail_crawler = detail_crawler or crawler
        self.vendor_crawler = vendor_crawler
        self.sink = sink
        self.sql_filter = sql_filter
        self.title_filter = TitleFilter(product_filter or ProductFilter())
        self.logger = logger or logging.getLogger("pymarket_scrapper.workflow")
        self.vendors = VendorResolver(vendor_crawler, sink, self.logger)
        self.catalog_limit = catalog_limit

    # ------------------------------------------------------------------ modes
    async def run(
        self,
        mode: ExtractionMode,
        search_term: str,
        limit: int = 50,
        sort_strategy: Optional[str] = None,
        storefront_products: bool = False,
        recursive_vendors: bool = False,
        run_request: Optional[ExtractionRunRequest] = None,
    ) -> PipelineStats:
        """Execute one extraction job and return the search pipeline counts.

        When ``run_request`` is given and the sink is a ``RunTracker``, the job
        is recorded as an extraction run with one search; products loaded by
        the search pipeline are recorded as observations of that search.
        """
        tracker = self.sink if run_request and isinstance(self.sink, RunTracker) else None
        stats = PipelineStats()
        if tracker is not None:
            tracker.start_run(run_request)
        try:
            if tracker is not None:
                tracker.start_search(search_term, sort_strategy, limit)
            stats = await self._run_search(mode, search_term, limit, sort_strategy)
            if tracker is not None:
                tracker.finish_search("succeeded", stats.extracted)

            # "all" always includes the vendors' storefront catalogs.
            if storefront_products or mode is ExtractionMode.ALL:
                await self.process_vendor_catalogs()
            else:
                self.logger.info(
                    "catalog extraction skipped because --storefront-products was not supplied"
                )
            if recursive_vendors:
                await self.backfill_product_vendors()
        except BaseException as exc:
            if tracker is not None:
                tracker.finish_run("failed", stats.extracted, f"{type(exc).__name__}: {exc}")
            raise
        if tracker is not None:
            tracker.finish_run("succeeded", stats.extracted)
        return stats

    async def _run_search(
        self, mode: ExtractionMode, search_term: str, limit: int,
        sort_strategy: Optional[str],
    ) -> PipelineStats:
        stream = self.crawler.extract_search_items(
            search_term, limit=limit, sort_strategy=sort_strategy
        )
        if mode is ExtractionMode.PRODUCT:
            return await self.persist_search_products(stream)
        if mode is ExtractionMode.VENDOR:
            return await self.resolve_vendors(stream)
        return await self.enrich_and_persist(stream)

    async def persist_search_products(self, stream: AsyncIterator[ProductItem]) -> PipelineStats:
        """Search-only mode: dedupe, filter and persist without detail requests."""
        return await (
            Pipeline[ProductItem]()
            .add_step(Deduplicator[ProductItem](key_field="product_id"))
            .add_step(self.sql_filter)
            .set_sink(self.sink)
            .run(stream)
        )

    async def enrich_and_persist(self, stream: AsyncIterator[ProductItem]) -> PipelineStats:
        """Full mode: filter, dedupe, enrich from detail pages, resolve vendors, persist."""
        return await (
            Pipeline[ProductItem]()
            .add_step(self.title_filter)
            .add_step(Deduplicator[ProductItem](key_field="product_id"))
            .add_step(self._enrich)
            .add_step(self.sql_filter)
            .set_sink(self.sink)
            .run(stream)
        )

    async def resolve_vendors(self, stream: AsyncIterator[ProductItem]) -> PipelineStats:
        """Vendor mode: resolve vendors from matching search products, without
        persisting the search products themselves.

        Product detail extraction is attempted for every matching item (repeated
        product IDs included); only vendor pages are cached.
        """
        try:
            return await (
                Pipeline[ProductItem]()
                .add_step(self.title_filter)
                .add_step(self._resolve_only)
                .run(stream)
            )
        finally:
            self._log_vendor_summary()

    # ----------------------------------------------------------------- stages
    async def _details(self, product: ProductItem) -> Optional[dict[str, Any]]:
        """Fetch detail fields for one product, logging (not raising) failures."""
        if not product.url:
            self.logger.warning("Skipping detail extraction for %s without URL", product.product_id)
            return None
        try:
            details = await self.detail_crawler.extract_product_info(str(product.url))
        except Exception:
            self.logger.exception("Detail extraction failed for product %s", product.product_id)
            return None
        if not isinstance(details, dict):
            self.logger.error("Detail extraction for %s did not return a mapping", product.product_id)
            return None
        return details

    async def _resolve_vendor_safely(
        self, vendor_id: Any, vendor_url: Any, product_id: str
    ) -> Optional[dict[str, Any]]:
        """Return the persisted vendor, or ``None`` when it could not be saved."""
        if not vendor_id or (not vendor_url and str(vendor_id) not in self.vendors.cache):
            self.logger.warning("Product %s has no vendor ID or vendor URL", product_id)
            return None
        try:
            return await self.vendors.resolve(vendor_id, vendor_url)
        except Exception:
            self.vendors.stats.failures += 1
            self.logger.exception("Unable to resolve vendor for product %s", product_id)
            return None

    async def _enrich(self, stream: AsyncIterator[ProductItem]) -> AsyncIterator[ProductItem]:
        async for product in stream:
            details = await self._details(product)
            if details is None:
                # Keep the search-page data even when the detail page failed.
                yield product
                continue
            vendor = await self._resolve_vendor_safely(
                details.get("vendor_id"), details.get("vendor_url"), product.product_id
            )
            # products.vendor_id is a foreign key: only reference a vendor row
            # that exists, otherwise the product upsert would fail the run.
            details = {**details, "vendor_id": vendor["vendor_id"] if vendor else None}
            yield merge_product_details(product, details)

    async def _resolve_only(self, stream: AsyncIterator[ProductItem]) -> AsyncIterator[ProductItem]:
        async for product in stream:
            details = await self._details(product)
            if details is not None:
                await self._resolve_vendor_safely(
                    details.get("vendor_id"), details.get("vendor_url"), product.product_id
                )
            yield product

    def _log_vendor_summary(self) -> None:
        stats = self.vendors.stats
        self.logger.info(
            "Vendor resolution summary: unique vendors resolved=%d; cache hits=%d; failures=%d",
            stats.resolved,
            stats.cache_hits,
            stats.failures,
        )

    # -------------------------------------------------------- follow-up jobs
    async def process_vendor_catalogs(self) -> None:
        """Persist unique storefront products for every vendor resolved so far."""
        catalog_dedup = Deduplicator[ProductItem](key_field="product_id")
        for vendor_id, vendor in list(self.vendors.cache.items()):
            storefront_url = vendor.get("storefront_url") or (
                vendor.get("metadata") or {}
            ).get("storefront_url")
            if not storefront_url:
                self.logger.info(
                    "catalog extraction skipped vendor_id=%s reason=storefront_url_missing",
                    vendor_id,
                )
                continue
            catalog_url = urljoin(vendor.get("url") or "", storefront_url)
            self.logger.info("catalog extraction starts vendor_id=%s url=%s", vendor_id, catalog_url)
            await (
                Pipeline[ProductItem]()
                .add_step(catalog_dedup)
                .add_step(_assign_vendor(vendor_id))
                .set_sink(self.sink)
                .run(self.vendor_crawler.extract_vendor_catalog(catalog_url, limit=self.catalog_limit))
            )
            self.logger.info("catalog extraction completes vendor_id=%s", vendor_id)

    async def backfill_product_vendors(self) -> None:
        """Resolve vendors for persisted products whose ``vendor_id`` is NULL."""
        iter_rows = getattr(self.sink, "iter_products_without_vendor", None)
        update = getattr(self.sink, "update_product_vendor", None)
        if iter_rows is None or update is None:
            raise TypeError("sink does not support vendor backfill")
        for row in iter_rows():
            product_id = str(row["product_id"])
            if not row.get("url"):
                self.logger.warning("Cannot backfill product %s without URL", product_id)
                continue
            try:
                details = await self.detail_crawler.extract_product_info(str(row["url"]))
                vendor = await self.vendors.resolve(
                    details.get("vendor_id"), details.get("vendor_url")
                )
                if vendor is None:
                    self.logger.warning("No vendor found for product %s", product_id)
                    continue
                update(product_id, vendor["vendor_id"])
            except Exception:
                self.logger.exception("Unable to backfill vendor for product %s", product_id)


def _assign_vendor(vendor_id: str):
    async def stage(stream: AsyncIterator[ProductItem]) -> AsyncIterator[ProductItem]:
        async for product in stream:
            yield product.model_copy(update={"vendor_id": vendor_id})

    return stage
