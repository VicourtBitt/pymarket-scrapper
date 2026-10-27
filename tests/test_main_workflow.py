import asyncio
from collections.abc import AsyncIterator
from typing import Any

from models import ProductItem
from main import run_amazon_workflow


class FakeCrawler:
    def __init__(self) -> None:
        self.product_urls: list[str] = []
        self.vendor_urls: list[str] = []
        self.catalog_urls: list[str] = []

    async def extract_product_info(self, product_url: str) -> dict[str, Any]:
        self.product_urls.append(product_url)
        return {
            "url": product_url,
            "title": f"Detailed {product_url}",
            "price": 12.5,
            "currency": "USD",
            "vendor_id": "vendor-1",
            "vendor_url": "https://example.test/vendor-1",
            "details": {},
            "description": None,
            "features": [],
            "reviews": [],
        }

    async def extract_vendor_info(self, vendor_url: str) -> dict[str, Any]:
        self.vendor_urls.append(vendor_url)
        return {
            "vendor_url": vendor_url,
            "name": "Example Vendor",
            "storefront_url": "https://example.test/vendor-1/catalog",
            "seller_info": {},
        }

    async def extract_vendor_catalog(self, vendor_url: str) -> AsyncIterator[ProductItem]:
        self.catalog_urls.append(vendor_url)
        yield ProductItem(
            product_id="catalog-1",
            title="Catalog product",
            url="https://example.test/catalog-1",
            price=5.0,
            currency="USD",
            vendor_id=None,
        )


class FakeSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def load_vendor(self, vendor: dict[str, Any]) -> None:
        self.events.append(("vendor", vendor))

    def load_product(self, product: dict[str, Any]) -> None:
        self.events.append(("product", product))


class PassThroughFilter:
    async def process(self, stream: AsyncIterator[ProductItem]) -> AsyncIterator[ProductItem]:
        async for item in stream:
            yield item


async def search_products() -> AsyncIterator[ProductItem]:
    for product_id in ("product-1", "product-1", "product-2"):
        yield ProductItem(
            product_id=product_id,
            title="Search product",
            url=f"https://example.test/{product_id}",
            price=1.0,
            currency="USD",
            vendor_id=None,
        )


def test_amazon_workflow_enriches_and_deduplicates_related_requests() -> None:
    crawler = FakeCrawler()
    sink = FakeSink()

    asyncio.run(
        run_amazon_workflow(
            crawler, sink, search_products(), PassThroughFilter()  # type: ignore[arg-type]
        )
    )

    assert crawler.product_urls == [
        "https://example.test/product-1",
        "https://example.test/product-2",
    ]
    assert crawler.vendor_urls == ["https://example.test/vendor-1"]
    assert crawler.catalog_urls == ["https://example.test/vendor-1/catalog"]
    assert [kind for kind, _ in sink.events] == ["vendor", "product", "product", "product"]
    assert sink.events[-1][1]["vendor_id"] == "vendor-1"
    assert sink.events[1][1]["title"] == "Detailed https://example.test/product-1"