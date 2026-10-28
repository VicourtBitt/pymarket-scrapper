import asyncio
import logging
import os
from enum import Enum
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any, Optional
from urllib.parse import urljoin

from playwright.async_api import async_playwright
import typer

from crawlers import AmazonCrawler
from include import LocalizedSanitization, load_environment
from include import configure_logging
from models import ProductItem
from models.config import MarketplaceConfig, ProductFilter
from pipeline import Deduplicator, Pipeline, PostgreSQLSink, SQLFilter


def _seller_info_name(seller_info: Any) -> Optional[str]:
    """Return a meaningful name or legal-name value from seller info."""
    if not isinstance(seller_info, dict):
        return None
    for key, value in seller_info.items():
        if not isinstance(key, str) or value is None:
            continue
        candidate = str(value).strip()
        if not candidate:
            continue
        normalized_key = " ".join(
            key.casefold().replace("-", " ").replace("_", " ").split()
        ).rstrip(":").strip()
        if normalized_key in {
            "name", "nome", "legal name", "nome legal", "business name",
            "nome comercial", "razão social",
        } or "legal name" in normalized_key or "nome comercial" in normalized_key:
            return candidate
    return None


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
    extracted_name = details.get("name")
    name = str(extracted_name).strip() if extracted_name is not None else ""
    if not name:
        name = _seller_info_name(seller_info) or ""
    if not name:
        logging.getLogger("pymarket_scrapper.workflow").warning(
            "Vendor %s has no meaningful extracted seller name; using vendor ID",
            vendor_id,
        )
        name = vendor_id
    cnpj = None
    if isinstance(seller_info, dict):
        for key, value in seller_info.items():
            if isinstance(key, str) and key.strip().rstrip(":").strip().casefold() == "cnpj":
                if value is not None:
                    cnpj = str(value).strip() or None
                break

    normalized = {
        "vendor_id": vendor_id,
        "name": name,
        "url": details.get("vendor_url") or vendor_url,
        "cnpj": cnpj,
        "storefront_url": details.get("storefront_url"),
        "metadata": {
            "storefront_url": details.get("storefront_url"),
            "seller_info": seller_info,
        },
    }
    logging.getLogger("pymarket_scrapper.workflow").info(
        "normalized vendor before persistence vendor_id=%s name_present=%s "
        "cnpj_present=%s storefront_present=%s",
        vendor_id,
        bool(normalized["name"]),
        bool(normalized["cnpj"]),
        bool(normalized["metadata"]["storefront_url"]),
    )
    return normalized


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
                logger.info(
                    "vendor persistence completed vendor_id=%s", vendor_id
                )
                vendor_cache[vendor_id] = normalized_vendor
        elif not vendor_id:
            logger.warning("Product %s has no vendor ID", search_product.product_id)

        yield ProductItem(**product_data)


async def _filter_search_products(
    search_stream: AsyncIterator[ProductItem],
    product_filter: ProductFilter,
) -> AsyncIterator[ProductItem]:
    """Yield only search products matching the configured title filter."""
    async for product in search_stream:
        if product_filter.matches(product.title):
            yield product


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
        storefront_url = vendor_data.get("storefront_url")
        if not storefront_url:
            storefront_url = vendor_data.get("metadata", {}).get("storefront_url")
        if not storefront_url:
            logger.info(
                "catalog extraction skipped vendor_id=%s reason=storefront_url_missing",
                vendor_id,
            )
            continue
        catalog_url = urljoin(vendor_url, storefront_url)
        logger.info(
            "catalog extraction starts vendor_id=%s url=%s", vendor_id, catalog_url
        )
        async for catalog_product in crawler.extract_vendor_catalog(catalog_url):
            if catalog_product.product_id in seen_catalog_products:
                continue
            seen_catalog_products.add(catalog_product.product_id)
            catalog_data = catalog_product.model_dump()
            catalog_data["vendor_id"] = vendor_id
            sink.load_product(catalog_data)
        logger.info("catalog extraction completes vendor_id=%s", vendor_id)


async def run_amazon_workflow(
    crawler: AmazonCrawler,
    sink: PostgreSQLSink,
    search_stream: AsyncIterator[ProductItem],
    sql_filter: SQLFilter[ProductItem],
    logger: Optional[logging.Logger] = None,
    storefront_products: bool = True,
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
    if storefront_products:
        await _process_vendor_catalogs(crawler, sink, vendor_cache, workflow_logger)


async def _persist_search_products(
    search_stream: AsyncIterator[ProductItem],
    sink: PostgreSQLSink,
    sql_filter: SQLFilter[ProductItem],
) -> None:
    """Persist deduplicated search records without detail-page extraction.

    This deliberately consumes only the search stream. Vendor resolution and
    catalog crawling are separate opt-in workflows.
    """
    await Pipeline().add_step(Deduplicator[ProductItem](key_field="product_id")).add_step(
        sql_filter
    ).set_sink(sink).run(search_stream)


async def _resolve_vendors_from_search(
    crawler: AmazonCrawler,
    search_stream: AsyncIterator[ProductItem],
    sink: PostgreSQLSink,
    logger: logging.Logger,
) -> dict[str, dict[str, Any]]:
    """Resolve vendors from search results without writing search products.

    Product detail extraction is deliberately performed for every item in the
    stream (including repeated products).  Only successful vendor detail
    extraction is cached: this keeps this bounded streaming workflow honest
    while avoiding repeated requests for a vendor shared by several products.
    """
    cache: dict[str, dict[str, Any]] = {}
    products_considered = 0
    products_skipped_without_url = 0
    detail_extraction_failures = 0
    products_without_vendor_id_or_url = 0
    duplicate_vendor_hits = 0
    vendors_persisted = 0

    try:
        async for product in search_stream:
            products_considered += 1
            logger.info(
                "Vendor resolution: considering product %s (%d)",
                product.product_id,
                products_considered,
            )
            if not product.url:
                products_skipped_without_url += 1
                logger.warning(
                    "Skipping vendor resolution for product %s without URL",
                    product.product_id,
                )
                continue

            try:
                # Do not cache product details: every matching search result
                # must be attempted, even when its product ID is repeated.
                details = await crawler.extract_product_info(str(product.url))
                if not isinstance(details, dict):
                    raise TypeError("product detail extraction did not return a mapping")
                vendor_id = details.get("vendor_id")
                vendor_url = details.get("vendor_url")
                if not vendor_id or not vendor_url:
                    products_without_vendor_id_or_url += 1
                    logger.warning(
                        "Product %s has no vendor ID or vendor URL",
                        product.product_id,
                    )
                    continue

                vendor_key = str(vendor_id)
                if vendor_key in cache:
                    duplicate_vendor_hits += 1
                    logger.info(
                        "Vendor resolution: cached vendor hit vendor_id=%s "
                        "product_id=%s",
                        vendor_key,
                        product.product_id,
                    )
                    continue

                vendor_details = await crawler.extract_vendor_info(str(vendor_url))
                if not isinstance(vendor_details, dict):
                    raise TypeError("vendor detail extraction did not return a mapping")
                vendor = _vendor_data(vendor_key, str(vendor_url), vendor_details)
                logger.info(
                    "normalized vendor ready for persistence vendor_id=%s",
                    vendor_key,
                )
                sink.load_vendor(vendor)
                vendors_persisted += 1
                logger.info("vendor persistence completed vendor_id=%s", vendor_key)
                # Cache only after extraction and persistence succeed.  A
                # failed vendor page can therefore be retried by a later
                # product without retaining a partial result.
                cache[vendor_key] = vendor
            except Exception:
                detail_extraction_failures += 1
                logger.exception(
                    "Unable to resolve vendor for product %s", product.product_id
                )
    finally:
        logger.info(
            "Vendor resolution summary: products considered=%d; products "
            "skipped without URL=%d; detail extraction failures=%d; products "
            "without vendor ID/URL=%d; unique vendors resolved=%d; duplicate "
            "vendor hits=%d; vendors persisted=%d",
            products_considered,
            products_skipped_without_url,
            detail_extraction_failures,
            products_without_vendor_id_or_url,
            len(cache),
            duplicate_vendor_hits,
            vendors_persisted,
        )
    return cache


async def _backfill_product_vendors(
    crawler: AmazonCrawler,
    sink: PostgreSQLSink,
    logger: logging.Logger,
) -> None:
    """Resolve vendors for persisted products with a NULL vendor_id."""
    for row in sink.iter_products_without_vendor():
        if not row["url"]:
            logger.warning("Cannot backfill product %s without URL", row["product_id"])
            continue
        try:
            details = await crawler.extract_product_info(str(row["url"]))
            vendor_id, vendor_url = details.get("vendor_id"), details.get("vendor_url")
            if not vendor_id or not vendor_url:
                logger.warning("No vendor found for product %s", row["product_id"])
                continue
            vendor = _vendor_data(
                vendor_id, vendor_url, await crawler.extract_vendor_info(vendor_url)
            )
            logger.info("normalized vendor ready for persistence vendor_id=%s", vendor_id)
            sink.load_vendor(vendor)
            logger.info("vendor persistence completed vendor_id=%s", vendor_id)
            sink.update_product_vendor(str(row["product_id"]), vendor_id)
        except Exception:
            logger.exception("Unable to backfill vendor for product %s", row["product_id"])


class ExtractionMode(str, Enum):
    """Supported CLI extraction scopes."""
    PRODUCT = "product"
    VENDOR = "vendor"
    ALL = "all"


app = typer.Typer(help="Extract marketplace products and vendors.")


def _cli_product_filter(product_title_contains: Optional[str] = None) -> ProductFilter:
    """Build the CLI title filter, preferring an explicitly supplied value."""
    configured_title = (
        product_title_contains
        if product_title_contains is not None
        else os.getenv("PRODUCT_TITLE_CONTAINS")
    )
    title_contains = configured_title.strip() if configured_title else None
    return ProductFilter(title_contains=title_contains or None)


def _configured_log_level() -> int:
    """Return the requested logging level, falling back safely to INFO."""
    configured = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, configured, logging.INFO)
    return level if isinstance(level, int) else logging.INFO


async def _run_cli(
    extraction: ExtractionMode,
    search: str,
    limit: int,
    marketplace: str,
    sort_strategy: Optional[str],
    recursive_vendors: bool,
    storefront_products: bool,
    headless: bool,
    database_url: str,
    product_title_contains: Optional[str] = None,
) -> None:
    """Build the existing workflow dependencies and execute one CLI job."""
    logger = configure_logging(
        os.getenv("LOG_DIRECTORY", "logs"), level=_configured_log_level()
    )
    config = MarketplaceConfig.from_marketplace(marketplace, Path(
        os.getenv("MARKETPLACE_CONFIG_DIR", "configs")
    ))
    sink = PostgreSQLSink(database_url, marketplace=marketplace)
    product_filter = _cli_product_filter(product_title_contains)
    sql_filter = SQLFilter[ProductItem](
        model_class=ProductItem,
        filters=product_filter,
    )
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            try:
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                )
                page = await context.new_page()
                crawler = AmazonCrawler(
                    page,
                    sanitizer=LocalizedSanitization(decimal_separator=",", thousands_separator="."),
                    config=config,
                )
                stream = crawler.extract_search_items(search, limit=limit, sort_strategy=sort_strategy)
                if extraction is ExtractionMode.VENDOR:
                    filtered_stream = _filter_search_products(stream, product_filter)
                    vendors = await _resolve_vendors_from_search(
                        crawler, filtered_stream, sink, logger
                    )
                    if storefront_products:
                        logger.info(
                            "Vendor mode: about to process storefront catalogs"
                        )
                        await _process_vendor_catalogs(crawler, sink, vendors, logger)
                    else:
                        logger.info(
                            "Vendor mode: catalog extraction skipped because "
                            "--storefront-products was not supplied"
                        )
                elif extraction is ExtractionMode.PRODUCT:
                    await _persist_search_products(stream, sink, sql_filter)
                else:
                    filtered_stream = _filter_search_products(stream, product_filter)
                    await run_amazon_workflow(
                        crawler, sink, filtered_stream, sql_filter, logger,
                        storefront_products=True,
                    )
                if recursive_vendors:
                    await _backfill_product_vendors(crawler, sink, logger)
                logger.info("CLI workflow complete; beginning browser cleanup")
            finally:
                await browser.close()
    finally:
        sql_filter.close()
        sink.close()


@app.command()
def cli(
    extraction: ExtractionMode = typer.Option(ExtractionMode.PRODUCT, "--extraction"),
    search: str = typer.Option("sementes multi", "--search"),
    limit: int = typer.Option(50, "--limit", min=1),
    marketplace: str = typer.Option("amazon", "--marketplace"),
    sort_strategy: Optional[str] = typer.Option(None, "--sort-strategy"),
    recursive_vendors: bool = typer.Option(False, "--recursive-vendors"),
    storefront_products: bool = typer.Option(False, "--storefront-products"),
    headless: bool = typer.Option(False, "--headless/--no-headless"),
    database_url: Optional[str] = typer.Option(
        None, "--database-url", envvar="DATABASE_URL"
    ),
    product_title_contains: Optional[str] = typer.Option(
        None,
        "--product-title-contains",
        help=(
            "Filter products by a case-insensitive title substring. "
            "Defaults to PRODUCT_TITLE_CONTAINS; an empty value disables filtering."
        ),
    ),
) -> None:
    """Run an extraction job; all network and database work is deferred to execution."""
    if not database_url:
        raise typer.BadParameter("DATABASE_URL or --database-url is required")
    try:
        asyncio.run(_run_cli(
            extraction, search, limit, marketplace, sort_strategy,
            recursive_vendors, storefront_products, headless, database_url,
            product_title_contains,
        ))
    except Exception as exc:
        logging.getLogger("pymarket_scrapper.cli").exception("CLI extraction failed")
        raise typer.Exit(code=1) from exc


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
            filters=ProductFilter(
                title_contains=os.getenv("PRODUCT_TITLE_CONTAINS", "ISLA")
            ),
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
                        "sementes multi", limit=50, sort_strategy=None
                    )
                    await run_amazon_workflow(crawler, db_sink, stream, sql_filter, logger)
                finally:
                    await browser.close()
        finally:
            sql_filter.close()
    finally:
        db_sink.close()


if __name__ == "__main__":
    app()
