import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import async_playwright

from crawlers import AmazonCrawler
from include import LocalizedSanitization, load_environment
from include import configure_logging
from models import ProductItem
from models.config import MarketplaceConfig, ProductFilter
from pipeline import Deduplicator, Pipeline, PostgreSQLSink, SQLFilter


async def main() -> None:
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
                    pipeline = (
                        Pipeline()
                        .add_step(Deduplicator[ProductItem](key_field="product_id"))
                        .add_step(sql_filter)
                        .set_sink(db_sink)
                    )
                    await pipeline.run(stream)
                finally:
                    await browser.close()
        finally:
            sql_filter.close()
    finally:
        db_sink.close()


if __name__ == "__main__":
    asyncio.run(main())
