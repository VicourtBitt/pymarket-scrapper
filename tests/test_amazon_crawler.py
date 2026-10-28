import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright")

from crawlers.amazon import AmazonCrawler
from include import LocalizedSanitization
from models.config import MarketplaceConfig
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


class FakeLocator:
    def __init__(
        self,
        values: dict[str, Any] | None = None,
        count: int = 1,
        used_selectors: list[str] | None = None,
    ) -> None:
        self.values = values or {}
        self._count = count
        self.used_selectors = used_selectors

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return self._count

    async def all(self) -> list["FakeLocator"]:
        return [self]

    def locator(self, selector: str) -> "FakeLocator":
        if self.used_selectors is not None:
            self.used_selectors.append(selector)
        if selector not in self.values:
            return FakeLocator(count=0, used_selectors=self.used_selectors)
        return FakeLocator(
            self.values[selector], self._count, self.used_selectors
        )

    async def inner_text(self) -> str:
        return str(self.values.get("text", ""))

    async def get_attribute(self, name: str) -> str | None:
        return self.values.get(name)

    async def is_visible(self) -> bool:
        return False

    async def click(self) -> None:
        return None


class FakePage:
    def __init__(self) -> None:
        self.used_selectors: list[str] = []
        self.card = FakeLocator(
            {
                ".custom-title": {"text": "Configured title"},
                ".custom-url": {"href": "/dp/abc?tag=test#variant"},
                ".custom-price": {"text": "R$ 12,50"},
                "data-custom-id": "ABC",
            },
            used_selectors=self.used_selectors,
        )

    async def goto(self, url: str, **kwargs: Any) -> None:
        assert "s=best" in url

    async def wait_for_selector(self, selector: str) -> None:
        self.used_selectors.append(selector)

    def locator(self, selector: str) -> FakeLocator:
        self.used_selectors.append(selector)
        if selector == ".custom-card":
            return FakeLocator(
                count=1,
                values=self.card.values,
                used_selectors=self.used_selectors,
            )
        return FakeLocator(count=0)

    async def wait_for_timeout(self, milliseconds: int) -> None:
        return None


def test_amazon_uses_configured_selectors_and_sort_value(tmp_path: Path) -> None:
    config_file = tmp_path / "amazon.yml"
    config_file.write_text(
        """
marketplace: amazon
base_url: https://example.test/search
query_parameters:
  search_key: q
  sort_key: s
  sort_values:
    best_sellers: best
search_page:
  product_card: .custom-card
  sponsored_ad_tag: .custom-sponsored
  title: .custom-title
  url: .custom-url
  price: .custom-price
  id_attribute: data-custom-id
  next_page_button: .custom-next
vendor_page:
  name: .custom-vendor
""",
        encoding="utf-8",
    )
    config = MarketplaceConfig.from_marketplace("amazon", tmp_path)
    page = FakePage()
    crawler = AmazonCrawler(
        page, LocalizedSanitization(decimal_separator=",", thousands_separator="."),
        config,
    )

    async def collect() -> list[Any]:
        return [item async for item in crawler.extract_search_items(
            "seeds", limit=1, sort_strategy="best_sellers"
        )]

    products = asyncio.run(collect())
    assert products[0].title == "Configured title"
    assert str(products[0].url) == "https://example.test/dp/abc?tag=test#variant"
    assert ".custom-card" in page.used_selectors
    assert ".custom-title" in page.used_selectors
    assert ".custom-sponsored" in page.used_selectors


class DetailLocator:
    def __init__(
        self,
        text: str = "",
        attributes: dict[str, str] | None = None,
        children: dict[str, list["DetailLocator"]] | None = None,
        html: str | None = None,
    ) -> None:
        self.text = text
        self.attributes = attributes or {}
        self.children = children or {}
        self.html = html

    @property
    def first(self) -> "DetailLocator":
        return self

    async def count(self) -> int:
        return 1

    async def all(self) -> list["DetailLocator"]:
        return [self]

    def locator(self, selector: str) -> "DetailLocator":
        matches = self.children.get(selector, [])
        if not matches:
            return EmptyLocator()
        return CollectionLocator(matches)

    async def inner_text(self) -> str:
        return self.text

    async def inner_html(self) -> str:
        return self.html or self.text

    async def get_attribute(self, name: str) -> str | None:
        return self.attributes.get(name)


class EmptyLocator(DetailLocator):
    async def count(self) -> int:
        return 0

    async def all(self) -> list["DetailLocator"]:
        return []


class DetailPage:
    def __init__(self, values: dict[str, DetailLocator | list[DetailLocator]]) -> None:
        self.values = values
        self.urls: list[str] = []

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.urls.append(url)

    def locator(self, selector: str) -> DetailLocator:
        value = self.values.get(selector)
        if isinstance(value, list):
            return CollectionLocator(value)
        return value or EmptyLocator()


class CollectionLocator(DetailLocator):
    def __init__(self, values: list[DetailLocator]) -> None:
        super().__init__()
        self.values = values

    async def count(self) -> int:
        return len(self.values)

    async def all(self) -> list[DetailLocator]:
        return self.values

    @property
    def first(self) -> DetailLocator:
        return self.values[0] if self.values else EmptyLocator()


class NavigationPage(DetailPage):
    def __init__(
        self,
        values: dict[str, DetailLocator | list[DetailLocator]],
        timeout: bool = False,
    ) -> None:
        super().__init__(values)
        self.navigation_calls: list[tuple[str, dict[str, Any]]] = []
        self.timeout = timeout

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.navigation_calls.append((url, kwargs))
        if self.timeout:
            raise PlaywrightTimeoutError("navigation timeout")


def detail_config() -> MarketplaceConfig:
    return MarketplaceConfig.model_validate(
        {
            "marketplace": "amazon",
            "base_url": "https://example.test/s",
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
                "id_attribute": "data-asin",
                "next_page_button": ".next",
            },
            "vendor_page": {
                "name": ".vendor-name",
                "storefront_href": "#storefront a",
                "seller_info_row": "#page-section-detail-seller-info .a-box-inner > div.a-row.a-spacing-none",
                "seller_info_key": "span.a-text-bold",
                "seller_info_value": "span:not(.a-text-bold)",
            },
            "product_page": {
                "title": "#title",
                "price_whole": ".whole",
                "price_decimal": ".decimal",
                "price_fraction": ".fraction",
                "merchant_vendor_id": "#merchant",
                "details_row": ".detail-row",
                "details_cell": "td",
                "description": "#description",
            },
            "vendor_catalog_page": {
                "product_card": ".catalog-card",
                "product_id_attribute": "data-asin",
            },
        }
    )


def test_extracts_product_page_details() -> None:
    row = DetailLocator(children={"td": [DetailLocator("Brand"), DetailLocator("Acme")]})
    page = DetailPage(
        {
            "#title": DetailLocator("Configured product"),
            ".whole": DetailLocator("1."),
            ".decimal": DetailLocator(""),
            ".fraction": DetailLocator("234,50"),
            "#merchant": DetailLocator(attributes={"data-csa-c-asin": "SELLER1"}),
            ".detail-row": [row],
            "#description": DetailLocator(html="<p>Good <b>product</b></p><script>bad</script>"),
        }
    )
    crawler = AmazonCrawler(
        page, LocalizedSanitization(decimal_separator=",", thousands_separator="."),
        detail_config(),
    )

    product = asyncio.run(crawler.extract_product_info("/dp/abc?tag=test#variant"))

    assert page.urls == ["https://example.test/dp/abc?tag=test#variant"]
    assert product["url"] == "https://example.test/dp/abc?tag=test#variant"
    assert product["title"] == "Configured product"
    assert product["price"] == 1234.5
    assert product["vendor_id"] == "SELLER1"
    assert product["details"] == {"Brand": "Acme"}
    assert product["description"] == "Good product"


def test_product_and_vendor_diagnostic_stages_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    config = detail_config()
    page = DetailPage(
        {
            "#title": DetailLocator("Configured product"),
            "#merchant": DetailLocator(attributes={"data-csa-c-asin": "SELLER1"}),
            ".vendor-name": DetailLocator("Acme Store"),
            "#storefront a": DetailLocator(attributes={"href": "/stores/acme"}),
            "#page-section-detail-seller-info .a-box-inner > div.a-row.a-spacing-none": [
                DetailLocator(
                    children={
                        "span.a-text-bold": [DetailLocator("CNPJ:")],
                        "span:not(.a-text-bold)": [DetailLocator("private-value")],
                    }
                )
            ],
        }
    )
    crawler = AmazonCrawler(page, LocalizedSanitization(), config)

    with caplog.at_level(logging.DEBUG, logger="pymarket_scrapper.crawlers.amazon"):
        asyncio.run(crawler.extract_product_info("/dp/abc"))
        asyncio.run(crawler.extract_vendor_info("https://example.test/vendor"))

    messages = [record.getMessage() for record in caplog.records]
    assert any("product detail starts" in message for message in messages)
    assert any("product detail completes" in message for message in messages)
    assert any("extracted vendor fields vendor_id=SELLER1" in message for message in messages)
    assert any("vendor extraction starts" in message for message in messages)
    assert any("vendor page navigation completes" in message for message in messages)
    assert any("storefront selector inspected" in message for message in messages)
    assert any("seller rows count=1" in message for message in messages)
    assert any("key_present=True value_present=True" in message for message in messages)
    assert "private-value" not in "\n".join(messages)


def test_product_page_prefers_vendor_id_from_configured_vendor_link() -> None:
    config = detail_config()
    config.product_page.merchant_vendor_link = "#merchant-link"
    page = DetailPage(
        {
            "#title": DetailLocator("Configured product"),
            "#merchant-link": DetailLocator(
                attributes={"href": "/seller?SellerId=vendor-from-link"}
            ),
        }
    )
    crawler = AmazonCrawler(page, LocalizedSanitization(), config)

    product = asyncio.run(crawler.extract_product_info("/dp/abc"))

    assert product["vendor_id"] == "vendor-from-link"
    assert product["vendor_url"] == "https://example.test/seller?SellerId=vendor-from-link"


def test_product_page_ignores_javascript_vendor_link_and_uses_legacy_id() -> None:
    config = detail_config()
    config.product_page.merchant_vendor_link = "#merchant-link"
    page = DetailPage(
        {
            "#title": DetailLocator("Configured product"),
            "#merchant-link": DetailLocator(attributes={"href": "javascript:void(0)"}),
            "#merchant": DetailLocator(
                attributes={"data-csa-c-asin": "legacy-seller"}
            ),
        }
    )
    crawler = AmazonCrawler(page, LocalizedSanitization(), config)

    product = asyncio.run(crawler.extract_product_info("/dp/abc"))

    assert product["vendor_url"] is None
    assert product["vendor_id"] == "legacy-seller"
    assert page.urls == ["https://example.test/dp/abc"]


def test_extracts_vendor_info_and_catalog() -> None:
    seller_rows = [
        DetailLocator(
            children={
                "span.a-text-bold": [DetailLocator("Nome Comercial:")],
                "span:not(.a-text-bold)": [DetailLocator("TAZINHAMIX COMERCIO LTDA")],
            }
        ),
        DetailLocator(
            children={
                "span.a-text-bold": [DetailLocator("CNPJ:")],
                "span:not(.a-text-bold)": [DetailLocator("62.246.912/0001-03")],
            }
        ),
        DetailLocator(
            children={
                "span.a-text-bold": [DetailLocator("Número de telefone:")],
                "span:not(.a-text-bold)": [DetailLocator("31997606208")],
            }
        ),
        DetailLocator(
            children={"span.a-text-bold": [DetailLocator("Endereço:")]}
        ),
    ]
    card = DetailLocator(
        attributes={"data-asin": "ASIN1"},
        children={
            ".title": [DetailLocator("Catalog product")],
            "a": [DetailLocator(attributes={"href": "/dp/ASIN1"})],
            ".price": [DetailLocator("R$ 10,00")],
        },
    )
    page = DetailPage(
        {
            ".vendor-name": DetailLocator("Acme Store"),
            "#storefront a": DetailLocator(attributes={"href": "/stores/acme"}),
            "#page-section-detail-seller-info .a-box-inner > div.a-row.a-spacing-none": seller_rows,
            ".catalog-card": [card],
        }
    )
    crawler = AmazonCrawler(
        page, LocalizedSanitization(decimal_separator=",", thousands_separator="."),
        detail_config(),
    )

    vendor = asyncio.run(crawler.extract_vendor_info("https://example.test/vendor"))

    async def collect() -> list[Any]:
        return [item async for item in crawler.extract_vendor_catalog(
            "https://example.test/vendor"
        )]

    products = asyncio.run(collect())
    assert vendor["storefront_url"] == "https://example.test/stores/acme"
    assert vendor["seller_info"] == {
        "Nome Comercial:": "TAZINHAMIX COMERCIO LTDA",
        "CNPJ:": "62.246.912/0001-03",
        "Número de telefone:": "31997606208",
    }
    assert products[0].product_id == "ASIN1"
    assert products[0].title == "Catalog product"
    assert products[0].price == 10.0


def test_extracts_storefront_from_current_amazon_selector() -> None:
    config = detail_config()
    config.vendor_page.storefront_href = (
        "#seller-info-storefront-link a, #seller_info_storefront_link a"
    )
    page = DetailPage(
        {
            "#seller-info-storefront-link a": DetailLocator(
                attributes={
                    "href": (
                        "/s?ie=UTF8&marketplaceID=A2Q3Y263D00KWC"
                        "&me=A1RZY52AGFFK82"
                    )
                }
            )
        }
    )
    crawler = AmazonCrawler(page, LocalizedSanitization(), config)

    vendor = asyncio.run(
        crawler.extract_vendor_info("https://www.amazon.com.br/seller/example")
    )

    assert vendor["storefront_url"] == (
        "https://www.amazon.com.br/s?ie=UTF8&marketplaceID=A2Q3Y263D00KWC"
        "&me=A1RZY52AGFFK82"
    )


def test_storefront_alternatives_skip_invalid_href() -> None:
    config = detail_config()
    config.vendor_page.storefront_href = "#invalid a, #seller-info-storefront-link a"
    page = DetailPage(
        {
            "#invalid a": DetailLocator(attributes={"href": "javascript:void(0)"}),
            "#seller-info-storefront-link a": DetailLocator(
                attributes={"href": "/s?me=valid-seller"}
            ),
        }
    )
    crawler = AmazonCrawler(page, LocalizedSanitization(), config)

    vendor = asyncio.run(crawler.extract_vendor_info("https://example.test/vendor"))

    assert vendor["storefront_url"] == "https://example.test/s?me=valid-seller"


def test_vendor_and_catalog_navigation_wait_for_bounded_dom_ready() -> None:
    card = DetailLocator(
        attributes={"data-asin": "ASIN1"},
        children={".title": [DetailLocator("Catalog product")]},
    )
    page = NavigationPage(
        {
            ".vendor-name": DetailLocator("Acme Store"),
            ".catalog-card": [card],
        }
    )
    crawler = AmazonCrawler(
        page, LocalizedSanitization(decimal_separator=",", thousands_separator="."),
        detail_config(),
    )

    asyncio.run(crawler.extract_vendor_info("https://example.test/vendor"))

    async def collect() -> list[Any]:
        return [item async for item in crawler.extract_vendor_catalog(
            "https://example.test/store"
        )]

    asyncio.run(collect())

    assert [call[1] for call in page.navigation_calls] == [
        {"wait_until": "domcontentloaded", "timeout": 30_000},
        {"wait_until": "domcontentloaded", "timeout": 30_000},
    ]


def test_navigation_timeout_keeps_extracting_seller_info() -> None:
    seller_row = DetailLocator(
        children={
            "span.a-text-bold": [DetailLocator("CNPJ:")],
            "span:not(.a-text-bold)": [DetailLocator("12.345.678/0001-90")],
        }
    )
    page = NavigationPage(
        {
            ".vendor-name": DetailLocator("Acme Store"),
            "#storefront a": DetailLocator(attributes={"href": "/stores/acme"}),
            "#page-section-detail-seller-info .a-box-inner > div.a-row.a-spacing-none": [
                seller_row
            ],
        },
        timeout=True,
    )
    crawler = AmazonCrawler(
        page, LocalizedSanitization(decimal_separator=",", thousands_separator="."),
        detail_config(),
    )

    vendor = asyncio.run(crawler.extract_vendor_info("https://example.test/vendor"))

    assert vendor["name"] == "Acme Store"
    assert vendor["storefront_url"] == "https://example.test/stores/acme"
    assert vendor["seller_info"] == {"CNPJ:": "12.345.678/0001-90"}
