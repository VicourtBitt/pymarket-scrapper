"""Offline tests for normalization and ExtractionWorkflow orchestration."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Optional

from models import ProductItem
from models.config import ProductFilter
from pipeline import ExtractionMode, ExtractionWorkflow, Pipeline
from pipeline.normalization import normalize_vendor


def _product(product_id: str, title: str = "Search product", url: Optional[str] = "auto") -> ProductItem:
    return ProductItem(
        product_id=product_id,
        title=title,
        url=f"https://example.test/{product_id}" if url == "auto" else url,
        price=1.0,
        currency="USD",
        vendor_id=None,
    )


# ------------------------------------------------------------ normalization
def test_vendor_data_extracts_exact_cnpj_key_and_preserves_seller_info() -> None:
    seller_info = {
        "  cNpJ:  ": " 62.246.912/0001-03 ",
        "CNPJ emissor": "not-the-vendor-cnpj",
    }

    vendor = normalize_vendor("vendor-1", "https://example.test/vendor-1", {"seller_info": seller_info})

    assert vendor["cnpj"] == "62.246.912/0001-03"
    assert vendor["storefront_url"] is None
    assert vendor["metadata"]["seller_info"] is seller_info


def test_vendor_data_promotes_storefront_url_and_preserves_metadata_compatibility() -> None:
    storefront_url = "https://example.test/vendor-1/catalog"
    vendor = normalize_vendor(
        "vendor-1",
        "https://example.test/vendor-1",
        {"storefront_url": storefront_url, "seller_info": {}},
    )

    assert vendor["storefront_url"] == storefront_url
    assert vendor["metadata"]["storefront_url"] == storefront_url


def test_vendor_data_uses_seller_info_name_when_extracted_name_is_blank() -> None:
    vendor = normalize_vendor(
        "vendor-1",
        "https://example.test/vendor-1",
        {"name": "  ", "seller_info": {"Nome Comercial:": "  Acme Legal  "}},
    )

    assert vendor["name"] == "Acme Legal"


# ------------------------------------------------------------------- fakes
class FakeCrawler:
    def __init__(self, search: list[ProductItem], vendor_for: Any = None) -> None:
        self.search = search
        self.product_urls: list[str] = []
        self.vendor_for = vendor_for or (lambda url: "vendor-1")

    async def extract_search_items(self, *args: Any, **kwargs: Any) -> AsyncIterator[ProductItem]:
        for product in self.search:
            yield product

    async def extract_product_info(self, product_url: str) -> dict[str, Any]:
        self.product_urls.append(product_url)
        vendor_id = self.vendor_for(product_url)
        return {
            "url": product_url,
            "title": f"Detailed {product_url}",
            "price": 12.5,
            "currency": "USD",
            "vendor_id": vendor_id,
            "vendor_url": f"https://example.test/{vendor_id}" if vendor_id else None,
            "details": {},
            "description": None,
            "features": [],
            "reviews": [],
        }


class FakeVendorCrawler:
    def __init__(self, storefront: Optional[str] = "/catalog") -> None:
        self.vendor_urls: list[str] = []
        self.catalog_urls: list[str] = []
        self.storefront = storefront

    async def extract_vendor_info(self, vendor_url: str) -> dict[str, Any]:
        self.vendor_urls.append(vendor_url)
        return {
            "vendor_url": vendor_url,
            "name": "Example Vendor",
            "storefront_url": f"{vendor_url}{self.storefront}" if self.storefront else None,
            "seller_info": {},
        }

    async def extract_vendor_catalog(self, catalog_url: str, limit: int = 50) -> AsyncIterator[ProductItem]:
        self.catalog_urls.append(catalog_url)
        yield _product("catalog-1", "Catalog product")
        yield _product("catalog-1", "Catalog product")


class FakeSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.orphans: list[dict[str, Any]] = []
        self.updates: list[tuple[str, str]] = []

    def load_vendor(self, vendor: dict[str, Any]) -> None:
        self.events.append(("vendor", vendor))

    def load_product(self, product: dict[str, Any]) -> None:
        self.events.append(("product", product))

    def iter_products_without_vendor(self):
        yield from self.orphans

    def update_product_vendor(self, product_id: str, vendor_id: str) -> None:
        self.updates.append((product_id, vendor_id))


class PassThroughFilter:
    async def process(self, stream: AsyncIterator[ProductItem]) -> AsyncIterator[ProductItem]:
        async for item in stream:
            yield item


def _workflow(crawler, vendor_crawler, sink, product_filter=None) -> ExtractionWorkflow:
    return ExtractionWorkflow(
        crawler=crawler,
        vendor_crawler=vendor_crawler,
        sink=sink,
        sql_filter=PassThroughFilter(),
        product_filter=product_filter,
        logger=logging.getLogger("test.workflow"),
    )


# ---------------------------------------------------------------- pipeline
def test_pipeline_accepts_function_steps_and_reports_counts() -> None:
    async def source() -> AsyncIterator[ProductItem]:
        for product_id in ("a", "b", "c"):
            yield _product(product_id)

    async def drop_b(stream: AsyncIterator[ProductItem]) -> AsyncIterator[ProductItem]:
        async for item in stream:
            if item.product_id != "b":
                yield item

    sink = FakeSink()
    stats = asyncio.run(Pipeline().add_step(drop_b).set_sink(sink).run(source()))

    assert (stats.extracted, stats.loaded) == (3, 2)
    assert [event[1]["product_id"] for event in sink.events] == ["a", "c"]


# ------------------------------------------------------------------- modes
def test_product_mode_deduplicates_without_detail_or_vendor_work() -> None:
    crawler = FakeCrawler([_product("p-1"), _product("p-1"), _product("p-2")])
    vendor_crawler = FakeVendorCrawler()
    sink = FakeSink()

    stats = asyncio.run(_workflow(crawler, vendor_crawler, sink).run(ExtractionMode.PRODUCT, "x"))

    assert [p["product_id"] for _, p in sink.events] == ["p-1", "p-2"]
    assert crawler.product_urls == []
    assert vendor_crawler.vendor_urls == []
    assert (stats.extracted, stats.loaded) == (3, 2)


def test_all_mode_enriches_resolves_each_vendor_once_and_crawls_catalogs() -> None:
    crawler = FakeCrawler([_product("p-1"), _product("p-1"), _product("p-2")])
    vendor_crawler = FakeVendorCrawler()
    sink = FakeSink()

    asyncio.run(_workflow(crawler, vendor_crawler, sink).run(ExtractionMode.ALL, "x"))

    assert crawler.product_urls == ["https://example.test/p-1", "https://example.test/p-2"]
    assert vendor_crawler.vendor_urls == ["https://example.test/vendor-1"]
    assert vendor_crawler.catalog_urls == ["https://example.test/vendor-1/catalog"]
    assert [kind for kind, _ in sink.events] == ["vendor", "product", "product", "product"]
    assert sink.events[1][1]["title"] == "Detailed https://example.test/p-1"
    # The duplicated catalog card is deduplicated and attributed to its vendor.
    assert sink.events[-1][1]["product_id"] == "catalog-1"
    assert sink.events[-1][1]["vendor_id"] == "vendor-1"


def test_title_filter_runs_before_detail_requests() -> None:
    crawler = FakeCrawler([_product("seeds", "Organic Seeds"), _product("tools", "Garden tools")])
    sink = FakeSink()

    asyncio.run(
        _workflow(crawler, FakeVendorCrawler(), sink, ProductFilter(title_contains="seeds"))
        .run(ExtractionMode.ALL, "x")
    )

    assert crawler.product_urls == ["https://example.test/seeds"]


def test_vendor_mode_attempts_each_product_caches_vendor_pages_and_skips_products(caplog) -> None:
    def vendor_for(url: str) -> Optional[str]:
        if url.endswith("missing"):
            return None
        return "vendor-1" if url.endswith(("one", "two")) else "vendor-2"

    crawler = FakeCrawler(
        [
            _product("no-url", url=None),
            _product("one"),
            _product("two"),
            _product("three"),
            _product("missing"),
        ],
        vendor_for=vendor_for,
    )
    vendor_crawler = FakeVendorCrawler()
    sink = FakeSink()
    caplog.set_level(logging.INFO, logger="test.workflow")

    workflow = _workflow(crawler, vendor_crawler, sink)
    asyncio.run(workflow.run(ExtractionMode.VENDOR, "x"))

    assert crawler.product_urls == [
        "https://example.test/one",
        "https://example.test/two",
        "https://example.test/three",
        "https://example.test/missing",
    ]
    assert vendor_crawler.vendor_urls == [
        "https://example.test/vendor-1",
        "https://example.test/vendor-2",
    ]
    assert set(workflow.vendors.cache) == {"vendor-1", "vendor-2"}
    assert [kind for kind, _ in sink.events] == ["vendor", "vendor"]
    assert vendor_crawler.catalog_urls == []
    assert (
        "Vendor resolution summary: unique vendors resolved=2; cache hits=1; failures=0"
        in caplog.messages
    )


def test_vendor_mode_crawls_catalogs_only_when_requested() -> None:
    crawler = FakeCrawler([_product("p-1")])
    vendor_crawler = FakeVendorCrawler()
    sink = FakeSink()

    asyncio.run(
        _workflow(crawler, vendor_crawler, sink).run(
            ExtractionMode.VENDOR, "x", storefront_products=True
        )
    )

    assert vendor_crawler.catalog_urls == ["https://example.test/vendor-1/catalog"]


def test_failed_vendor_page_is_not_cached_and_product_is_still_persisted() -> None:
    class FlakyVendorCrawler(FakeVendorCrawler):
        async def extract_vendor_info(self, vendor_url: str) -> dict[str, Any]:
            if not self.vendor_urls:
                self.vendor_urls.append(vendor_url)
                raise RuntimeError("blocked")
            return await super().extract_vendor_info(vendor_url)

    crawler = FakeCrawler([_product("p-1"), _product("p-2")])
    vendor_crawler = FlakyVendorCrawler()
    sink = FakeSink()

    workflow = _workflow(crawler, vendor_crawler, sink)
    asyncio.run(workflow.enrich_and_persist(crawler.extract_search_items()))

    assert len(vendor_crawler.vendor_urls) == 2
    assert [kind for kind, _ in sink.events] == ["product", "vendor", "product"]
    assert workflow.vendors.stats.failures == 1


def test_catalog_processing_skips_vendor_without_storefront() -> None:
    vendor_crawler = FakeVendorCrawler(storefront=None)
    sink = FakeSink()
    workflow = _workflow(FakeCrawler([]), vendor_crawler, sink)
    workflow.vendors.cache["v"] = {"url": "https://example.test/v", "storefront_url": None, "metadata": {}}

    asyncio.run(workflow.process_vendor_catalogs())

    assert vendor_crawler.catalog_urls == []
    assert sink.events == []


def test_catalog_processing_falls_back_to_legacy_metadata_storefront() -> None:
    vendor_crawler = FakeVendorCrawler()
    sink = FakeSink()
    workflow = _workflow(FakeCrawler([]), vendor_crawler, sink)
    workflow.vendors.cache["legacy-vendor"] = {
        "url": "https://example.test/legacy-vendor",
        "metadata": {"storefront_url": "/legacy-catalog"},
    }

    asyncio.run(workflow.process_vendor_catalogs())

    assert vendor_crawler.catalog_urls == ["https://example.test/legacy-catalog"]
    assert sink.events[0][1]["vendor_id"] == "legacy-vendor"


def test_backfill_resolves_vendors_through_the_shared_cache() -> None:
    crawler = FakeCrawler([])
    vendor_crawler = FakeVendorCrawler()
    sink = FakeSink()
    sink.orphans = [
        {"product_id": "a", "url": "https://example.test/a"},
        {"product_id": "b", "url": "https://example.test/b"},
        {"product_id": "c", "url": None},
    ]

    asyncio.run(_workflow(crawler, vendor_crawler, sink).backfill_product_vendors())

    assert sink.updates == [("a", "vendor-1"), ("b", "vendor-1")]
    assert vendor_crawler.vendor_urls == ["https://example.test/vendor-1"]
