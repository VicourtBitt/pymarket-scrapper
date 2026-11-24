"""Contract tests for the crawler class hierarchy."""

import asyncio

import pytest

pytest.importorskip("playwright")

from crawlers import (
    AmazonCrawler,
    AmazonVendorCrawler,
    BaseCrawler,
    BaseVendorCrawler,
    MercadoLibreCrawler,
    MercadoLibreVendorCrawler,
)
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


def test_product_and_vendor_crawlers_are_separate_responsibilities() -> None:
    assert issubclass(AmazonCrawler, BaseCrawler)
    assert issubclass(AmazonVendorCrawler, BaseVendorCrawler)
    assert not hasattr(AmazonCrawler, "extract_vendor_info")
    assert not hasattr(AmazonVendorCrawler, "extract_search_items")


def test_vendor_crawler_shares_injected_sanitizer_and_config() -> None:
    sanitizer = LocalizedSanitization(decimal_separator=",", thousands_separator=".")
    page = object()
    product = AmazonCrawler(page, sanitizer, CONFIG)  # type: ignore[arg-type]
    vendor = AmazonVendorCrawler(page, sanitizer, CONFIG)  # type: ignore[arg-type]

    assert vendor.sanitizer is product.sanitizer
    assert vendor.config is product.config
    assert vendor.marketplace_name == "amazon"


def test_mercado_libre_placeholders_are_instantiable_and_explicit() -> None:
    sanitizer = LocalizedSanitization()
    crawler = MercadoLibreCrawler(object(), sanitizer, CONFIG)  # type: ignore[arg-type]
    vendor = MercadoLibreVendorCrawler(object(), sanitizer, CONFIG)  # type: ignore[arg-type]

    async def collect() -> None:
        async for _ in crawler.extract_search_items("x"):
            pass

    with pytest.raises(NotImplementedError):
        asyncio.run(collect())
    with pytest.raises(NotImplementedError):
        asyncio.run(vendor.extract_vendor_info("https://example.test"))
