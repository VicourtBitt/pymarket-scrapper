"""Typer entry point: build dependencies and run one ``ExtractionWorkflow``."""

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

import typer
from playwright.async_api import async_playwright

from crawlers import AmazonCrawler, AmazonVendorCrawler
from include import LocalizedSanitization, configure_logging, load_environment
from models import ExtractionRunRequest, ProductItem
from models.config import MarketplaceConfig, ProductFilter
from pipeline import ExtractionMode, ExtractionWorkflow, PostgreSQLSink, SQLFilter

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


def _run_request(
    marketplace: str,
    config: MarketplaceConfig,
    extraction: ExtractionMode,
    storefront_products: bool,
    recursive_vendors: bool,
    product_filter: ProductFilter,
) -> ExtractionRunRequest:
    """Describe this CLI job for the ``extraction_runs`` table."""
    config_json = config.model_dump_json() if hasattr(config, "model_dump_json") else ""
    return ExtractionRunRequest(
        marketplace=marketplace,
        source="cli",
        config_hash=hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
        metadata={
            "extraction": extraction.value,
            "storefront_products": storefront_products,
            "recursive_vendors": recursive_vendors,
            "product_title_contains": product_filter.title_contains,
        },
    )


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
    """Build the workflow dependencies and execute one CLI job."""
    logger = configure_logging(
        os.getenv("LOG_DIRECTORY", "logs"), level=_configured_log_level()
    )
    config = MarketplaceConfig.from_marketplace(
        marketplace, Path(os.getenv("MARKETPLACE_CONFIG_DIR", "configs"))
    )
    sink = PostgreSQLSink(database_url, marketplace=marketplace)
    product_filter = _cli_product_filter(product_title_contains)
    sql_filter = SQLFilter[ProductItem](model_class=ProductItem, filters=product_filter)
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
                sanitizer = LocalizedSanitization(
                    decimal_separator=",", thousands_separator="."
                )
                workflow = ExtractionWorkflow(
                    crawler=AmazonCrawler(page, sanitizer, config),
                    vendor_crawler=AmazonVendorCrawler(page, sanitizer, config),
                    sink=sink,
                    sql_filter=sql_filter,
                    product_filter=product_filter,
                    logger=logger,
                )
                await workflow.run(
                    extraction,
                    search,
                    limit=limit,
                    sort_strategy=sort_strategy,
                    storefront_products=storefront_products,
                    recursive_vendors=recursive_vendors,
                    run_request=_run_request(
                        marketplace, config, extraction, storefront_products,
                        recursive_vendors, product_filter,
                    ),
                )
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
    marketplace: str = typer.Option("amazon", "--marketplace", envvar="MARKETPLACE"),
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


if __name__ == "__main__":
    load_environment()
    app()
