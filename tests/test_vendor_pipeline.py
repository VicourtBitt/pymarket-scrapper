"""Focused tests for the intentionally deferred vendor interface."""

import asyncio

import pytest

pytest.importorskip("playwright")

from crawlers.vendor import AmazonVendorCrawler
from include import LocalizedSanitization
from models.config import MarketplaceConfig


CONFIG = MarketplaceConfig.model_validate(
    {
        "marketplace": "amazon",
        "query_parameters": {
            "search_key": "q",
            "sort_key": "s",
            "sort_values": {"best_sellers": "best"},
        },
        "search_page": {
            "product_card": ".card",
            "sponsored_ad_tag": ".ad",
            "title": ".title",
            "url": "a",
            "price": ".price",
            "id_attribute": "data-id",
            "next_page_button": ".next",
        },
        "vendor_page": {"name": ".vendor"},
    }
)


def test_vendor_module_imports_and_extraction_is_explicitly_deferred() -> None:
    crawler = AmazonVendorCrawler(
        object(),  # The placeholder must not touch Playwright.
        LocalizedSanitization(decimal_separator=",", thousands_separator="."),
        CONFIG,
    )

    async def collect() -> None:
        async for _ in crawler.extract_profile("https://example.test/vendor"):
            pass

    with pytest.raises(NotImplementedError, match="intentionally deferred"):
        asyncio.run(collect())
