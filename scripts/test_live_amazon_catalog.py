"""Manually test extraction from a live Amazon vendor catalog.

Usage:
    CATALOG_URL='https://www.amazon.com.br/s?me=SELLER_ID' \
    CATALOG_LIMIT=10 \
    PYTHONPATH=. ./venv/bin/python scripts/test_live_amazon_catalog.py
"""

import asyncio
import json
import os

from playwright.async_api import async_playwright

from live_amazon_common import create_crawler, required_url


async def main() -> None:
    limit = int(os.getenv("CATALOG_LIMIT", "10"))
    if limit < 1:
        raise ValueError("CATALOG_LIMIT must be greater than zero")

    async with async_playwright() as playwright:
        browser, _, crawler = await create_crawler(playwright)
        try:
            products = [
                item.model_dump(mode="json")
                async for item in crawler.extract_vendor_catalog(
                    required_url("CATALOG_URL"),
                    limit=limit,
                )
            ]
            print(json.dumps(products, ensure_ascii=False, indent=2))
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
