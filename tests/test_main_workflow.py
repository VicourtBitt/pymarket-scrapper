import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from models import ProductItem
from models.config import ProductFilter
from main import (
    _filter_search_products,
    _resolve_vendors_from_search,
    _vendor_data,
    run_amazon_workflow,
)


def test_vendor_data_extracts_exact_cnpj_key_and_preserves_seller_info() -> None:
    seller_info = {
        "  cNpJ:  ": " 62.246.912/0001-03 ",
        "CNPJ emissor": "not-the-vendor-cnpj",
    }

    vendor = _vendor_data(
        "vendor-1",
        "https://example.test/vendor-1",
        {"seller_info": seller_info},
    )

    assert vendor["cnpj"] == "62.246.912/0001-03"
    assert vendor["storefront_url"] is None
    assert vendor["metadata"]["seller_info"] is seller_info


def test_vendor_data_promotes_storefront_url_and_preserves_metadata_compatibility() -> None:
    storefront_url = "https://example.test/vendor-1/catalog"
    vendor = _vendor_data(
        "vendor-1",
        "https://example.test/vendor-1",
        {"storefront_url": storefront_url, "seller_info": {}},
    )

    assert vendor["storefront_url"] == storefront_url
    assert vendor["metadata"]["storefront_url"] == storefront_url


def test_vendor_data_uses_seller_info_name_when_extracted_name_is_blank() -> None:
    vendor = _vendor_data(
        "vendor-1",
        "https://example.test/vendor-1",
        {"name": "  ", "seller_info": {"Nome Comercial:": "  Acme Legal  "}},
    )

    assert vendor["name"] == "Acme Legal"


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


async def _titles() -> AsyncIterator[ProductItem]:
    for product_id, title in (("matching", "Organic Seeds"), ("other", "Garden tools")):
        yield ProductItem(
            product_id=product_id,
            title=title,
            url=f"https://example.test/{product_id}",
            price=1.0,
            currency="USD",
            vendor_id=None,
        )


def test_product_filter_can_be_applied_before_detail_requests() -> None:
    async def collect() -> list[ProductItem]:
        return [
            product
            async for product in _filter_search_products(
                _titles(), ProductFilter(title_contains="seeds")
            )
        ]

    products = asyncio.run(collect())

    assert [product.product_id for product in products] == ["matching"]


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


def test_catalog_processing_skips_vendor_without_storefront() -> None:
    crawler = FakeCrawler()
    sink = FakeSink()
    logger = logging.getLogger("test")
    vendors = {
        "vendor-without-storefront": {
            "url": "https://example.test/vendor-without-storefront",
            "storefront_url": None,
            "metadata": {"storefront_url": None},
        }
    }

    from main import _process_vendor_catalogs

    asyncio.run(_process_vendor_catalogs(crawler, sink, vendors, logger))

    assert crawler.catalog_urls == []
    assert sink.events == []


def test_catalog_processing_falls_back_to_legacy_metadata_storefront() -> None:
    crawler = FakeCrawler()
    sink = FakeSink()
    logger = logging.getLogger("test")
    vendors = {
        "legacy-vendor": {
            "url": "https://example.test/legacy-vendor",
            "metadata": {"storefront_url": "/legacy-catalog"},
        }
    }

    from main import _process_vendor_catalogs

    asyncio.run(_process_vendor_catalogs(crawler, sink, vendors, logger))

    assert crawler.catalog_urls == ["https://example.test/legacy-catalog"]
    assert sink.events[0][1]["vendor_id"] == "legacy-vendor"


def test_vendor_resolution_attempts_each_product_and_caches_only_vendor_pages(
    caplog,
) -> None:
    class MultiVendorCrawler:
        def __init__(self) -> None:
            self.product_urls: list[str] = []
            self.vendor_urls: list[str] = []

        async def extract_product_info(self, product_url: str) -> dict[str, Any]:
            self.product_urls.append(product_url)
            vendor_id = "vendor-1" if product_url.endswith(("one", "two")) else "vendor-2"
            return {
                "vendor_id": None if product_url.endswith("missing") else vendor_id,
                "vendor_url": (
                    None if product_url.endswith("missing")
                    else f"https://example.test/{vendor_id}"
                ),
            }

        async def extract_vendor_info(self, vendor_url: str) -> dict[str, Any]:
            self.vendor_urls.append(vendor_url)
            return {"vendor_url": vendor_url, "name": vendor_url, "seller_info": {}}

    async def products() -> AsyncIterator[ProductItem]:
        for product_id, url in (
            ("no-url", None),
            ("one", "https://example.test/one"),
            ("two", "https://example.test/two"),
            ("three", "https://example.test/three"),
            ("missing", "https://example.test/missing"),
        ):
            yield ProductItem(
                product_id=product_id,
                title=product_id,
                url=url,
                price=1.0,
                currency="USD",
                vendor_id=None,
            )

    crawler = MultiVendorCrawler()
    sink = FakeSink()
    logger = logging.getLogger("test.vendor-resolution")
    caplog.set_level(logging.INFO, logger=logger.name)

    vendors = asyncio.run(
        _resolve_vendors_from_search(crawler, products(), sink, logger)
    )

    assert crawler.product_urls == [
        "https://example.test/one",
        "https://example.test/two",
        "https://example.test/three",
        "https://example.test/missing",
    ]
    assert crawler.vendor_urls == [
        "https://example.test/vendor-1",
        "https://example.test/vendor-2",
    ]
    assert set(vendors) == {"vendor-1", "vendor-2"}
    assert caplog.messages[-1] == (
        "Vendor resolution summary: products considered=5; "
        "products skipped without URL=1; detail extraction failures=0; "
        "products without vendor ID/URL=1; unique vendors resolved=2; "
        "duplicate vendor hits=1; vendors persisted=2"
    )