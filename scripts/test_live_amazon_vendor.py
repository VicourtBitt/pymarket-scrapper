"""Manually test extraction from one live Amazon vendor page.

Usage:
    VENDOR_URL='https://www.amazon.com.br/sp?seller=SELLER_ID' \
    PYTHONPATH=. ./venv/bin/python scripts/test_live_amazon_vendor.py
"""

import asyncio
import json

from playwright.async_api import async_playwright

from live_amazon_common import create_crawler, required_url


async def main() -> None:
    async with async_playwright() as playwright:
        browser, _, crawler = await create_crawler(playwright)
        try:
            result = await crawler.extract_vendor_info(required_url("VENDOR_URL"))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
