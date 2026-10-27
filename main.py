import asyncio
import logging
import os
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright

from crawlers import AmazonCrawler
from include import LocalizedSanitization, load_environment
from include import configure_logging
from models import ProductItem
from models.config import MarketplaceConfig, ProductFilter
from pipeline import Deduplicator, Pipeline, PostgreSQLSink, SQLFilter


def _product_data(search_product: ProductItem, details: dict[str, Any]) -> dict[str, Any]:
    """Merge search and detail-page data into the product sink contract.

    Args:
        search_product: Product emitted by the search-page crawler.
        details: Raw detail-page fields returned by the crawler.

    Returns:
        A dictionary suitable for constructing ``ProductItem`` and loading it
        through the product sink.
    """
    data = search_product.model_dump()
    data.update({key: value for key, value in details.items() if value is not None})
    data["product_id"] = search_product.product_id
    data["url"] = details.get("url") or search_product.url
    data["vendor_id"] = details.get("vendor_id") or search_product.vendor_id
    data["metadata"] = {
        **(search_product.metadata or {}),
        "details": details.get("details", {}),
        "description": details.get("description"),
        "features": details.get("features", []),
        "reviews": details.get("reviews", []),
    }
    return data


def _vendor_data(vendor_id: str, vendor_url: str, details: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw vendor fields for the sink's vendor contract.

    Args:
        vendor_id: Marketplace identifier for the vendor.
        vendor_url: URL used to resolve the vendor.
        details: Raw vendor fields returned by the crawler.

    Returns:
        A normalized vendor dictionary for ``PostgreSQLSink.load_vendor``.
    """
    seller_info = details.get("seller_info", {})
    cnpj = None
    if isinstance(seller_info, dict):
        for key, value in seller_info.items():
            if isinstance(key, str) and key.strip().rstrip(":").strip().casefold() == "cnpj":
                if value is not None:
                    cnpj = str(value).strip() or None
                break

    return {
        "vendor_id": vendor_id,
        "name": details.get("name") or vendor_id,
        "url": details.get("vendor_url") or vendor_url,
        "cnpj": cnpj,
        "metadata": {
            "storefront_url": details.get("storefront_url"),
            "seller_info": seller_info,
        },
    }


async def _enrich_search_products(
    search_stream: AsyncIterator[ProductItem],
    crawler: AmazonCrawler,
    sink: PostgreSQLSink,
    vendor_cache: dict[str, dict[str, Any]],
    logger: logging.Logger,
) -> AsyncIterator[ProductItem]:
    """Enrich products and resolve each vendor once while streaming.

    Args:
        search_stream: Asynchronous search results to enrich.
        crawler: Crawler used for product and vendor detail requests.
        sink: Sink used to persist newly resolved vendors.
        vendor_cache: Mutable vendor cache shared with catalog processing.
        logger: Logger used for skipped or incomplete records.

    Yields:
        Enriched ``ProductItem`` instances, with duplicate product IDs removed.

    Side Effects:
        Performs product and vendor page requests and persists resolved vendors.
    """
    seen_products: set[str] = set()
    async for search_product in search_stream:
        if search_product.product_id in seen_products:
            continue
        seen_products.add(search_product.product_id)
        if not search_product.url:
            logger.warning("Skipping product %s without a URL", search_product.product_id)
            continue

        details = await crawler.extract_product_info(str(search_product.url))
        product_data = _product_data(search_product, details)
        vendor_id = product_data.get("vendor_id")
        vendor_url = details.get("vendor_url")
        if vendor_id and vendor_id not in vendor_cache:
            if not vendor_url:
                logger.warning("Skipping vendor %s without a URL", vendor_id)
            else:
                vendor_details = await crawler.extract_vendor_info(vendor_url)
                normalized_vendor = _vendor_data(vendor_id, vendor_url, vendor_details)
                sink.load_vendor(normalized_vendor)
                vendor_cache[vendor_id] = normalized_vendor
        elif not vendor_id:
            logger.warning("Product %s has no vendor ID", search_product.product_id)

        yield ProductItem(**product_data)


async def _process_vendor_catalogs(
    crawler: AmazonCrawler,
    sink: PostgreSQLSink,
    vendor_cache: dict[str, dict[str, Any]],
    logger: logging.Logger,
) -> None:
    """Persist unique catalog products for vendors resolved in the search flow.

    Args:
        crawler: Crawler used to enumerate vendor catalog pages.
        sink: Sink receiving catalog products.
        vendor_cache: Resolved vendors and their storefront metadata.
        logger: Logger used when a vendor has no usable catalog URL.

    Side Effects:
        Performs catalog page requests and upserts catalog products.
    """
    seen_catalog_products: set[str] = set()
    for vendor_id, vendor_data in vendor_cache.items():
        vendor_url = vendor_data.get("url")
        storefront_url = vendor_data.get("metadata", {}).get("storefront_url")
        catalog_url = urljoin(vendor_url, storefront_url) if storefront_url else vendor_url
        if not catalog_url:
            logger.warning("Skipping catalog for vendor %s without a URL", vendor_id)
            continue
        async for catalog_product in crawler.extract_vendor_catalog(catalog_url):
            if catalog_product.product_id in seen_catalog_products:
                continue
            seen_catalog_products.add(catalog_product.product_id)
            catalog_data = catalog_product.model_dump()
            catalog_data["vendor_id"] = vendor_id
            sink.load_product(catalog_data)


async def run_amazon_workflow(
    crawler: AmazonCrawler,
    sink: PostgreSQLSink,
    search_stream: AsyncIterator[ProductItem],
    sql_filter: SQLFilter[ProductItem],
    logger: Optional[logging.Logger] = None,
) -> None:
    """Run the Amazon search, enrichment, filtering, and catalog workflow.

    Args:
        crawler: Configured Amazon crawler.
        sink: Product and vendor persistence sink.
        search_stream: Asynchronous search stream from ``crawler``.
        sql_filter: Batch filter applied by the pipeline.
        logger: Optional logger for workflow warnings and diagnostics.

    Side Effects:
        Requests marketplace pages and writes vendors and products through
        ``sink``. Exceptions from the crawler, filter, or sink propagate.
    """
    workflow_logger = logger or logging.getLogger("pymarket_scrapper.workflow")
    vendor_cache: dict[str, dict[str, Any]] = {}
    enriched_stream = _enrich_search_products(
        search_stream, crawler, sink, vendor_cache, workflow_logger
    )
    await Pipeline().add_step(Deduplicator[ProductItem](key_field="product_id")).add_step(
        sql_filter
    ).set_sink(sink).run(enriched_stream)
    await _process_vendor_catalogs(crawler, sink, vendor_cache, workflow_logger)


async def main() -> None:
    """Configure dependencies and execute the interactive Amazon workflow.

    Raises:
        RuntimeError: If ``DATABASE_URL`` is not configured.
        ValueError: If marketplace configuration is invalid.

    Side Effects:
        Loads environment variables, opens a Playwright browser, performs
        network requests, and writes extracted records to the database.
    """
    load_environment()
    logger = configure_logging(os.getenv("LOG_DIRECTORY", "logs"))
    marketplace: str = os.getenv("MARKETPLACE", "amazon")
    configs_dir: Path = Path(os.getenv("MARKETPLACE_CONFIG_DIR", "configs"))
    config: MarketplaceConfig = MarketplaceConfig.from_marketplace(
        marketplace, configs_dir
    )
    db_url: Optional[str] = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL is not configured")
        raise RuntimeError(
            "DATABASE_URL is required; set it to a SQLAlchemy database URL"
        )

    def erp_matcher(vendor_data: dict[str, Any]) -> Optional[str]:
        vendor_name: str = str(vendor_data.get("name", "")).lower()
        if "official" in vendor_name:
            return f"ERP_PARTNER_{vendor_data['vendor_id']}"
        return None

    db_sink = PostgreSQLSink(
        connection_url=db_url,
        identity_resolver=erp_matcher,
        marketplace=marketplace,
    )
    try:
        sql_filter = SQLFilter[ProductItem](
            model_class=ProductItem,
            filters=ProductFilter(title_contains=os.getenv("PRODUCT_TITLE_CONTAINS", "Semente")),
        )
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=False)
                try:
                    context = await browser.new_context(
                        viewport={"width": 1280, "height": 720},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/114.0.0.0 Safari/537.36",
                    )
                    page = await context.new_page()
                    sanitizer = LocalizedSanitization(
                        decimal_separator=",", thousands_separator="."
                    )
                    crawler = AmazonCrawler(page, sanitizer=sanitizer, config=config)
                    stream = crawler.extract_search_items(
                        "sementes para plantar", limit=50, sort_strategy=None
                    )
                    await run_amazon_workflow(crawler, db_sink, stream, sql_filter, logger)
                finally:
                    await browser.close()
        finally:
            sql_filter.close()
    finally:
        db_sink.close()


if __name__ == "__main__":
    asyncio.run(main())
