"""Shared setup for manual Amazon extraction checks."""

import os
from pathlib import Path
import sys

from playwright.async_api import Browser, Page, Playwright

# Support direct execution such as ``python scripts/test_live_amazon_product.py``.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from crawlers.amazon import AmazonCrawler
from include import LocalizedSanitization, load_environment
from models.config import MarketplaceConfig


def required_url(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} to the Amazon URL to test")
    return value


async def create_crawler(
    playwright: Playwright,
) -> tuple[Browser, Page, AmazonCrawler]:
    load_environment()
    config = MarketplaceConfig.from_marketplace(
        os.getenv("MARKETPLACE", "amazon"),
        Path(os.getenv("MARKETPLACE_CONFIG_DIR", "configs")),
    )
    sanitizer = LocalizedSanitization(
        decimal_separator=",",
        thousands_separator=".",
        currency_fallback="BRL",
    )
    browser = await playwright.chromium.launch(
        headless=os.getenv("HEADLESS", "false").lower() == "true"
    )
    page = await browser.new_page(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        )
    )
    return browser, page, AmazonCrawler(page, sanitizer, config)
