import asyncio
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright")

from crawlers.amazon import AmazonCrawler
from include import LocalizedSanitization
from models.config import MarketplaceConfig


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
                ".custom-url": {"href": "/dp/abc"},
                ".custom-price": {"text": "R$ 12,50"},
                "data-custom-id": "ABC",
            },
            used_selectors=self.used_selectors,
        )

    async def goto(self, url: str) -> None:
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

    async def goto(self, url: str) -> None:
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


def detail_config() -> MarketplaceConfig:
    return MarketplaceConfig.model_validate(
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
                "id_attribute": "data-asin",
                "next_page_button": ".next",
            },
            "vendor_page": {
                "name": ".vendor-name",
                "storefront_href": "#storefront a",
                "seller_info_row": ".seller-row",
                "seller_info_key": ".key",
                "seller_info_value": ".value",
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

    product = asyncio.run(crawler.extract_product_info("https://example.test/product"))

    assert product["title"] == "Configured product"
    assert product["price"] == 1234.5
    assert product["vendor_id"] == "SELLER1"
    assert product["details"] == {"Brand": "Acme"}
    assert product["description"] == "Good product"


def test_extracts_vendor_info_and_catalog() -> None:
    seller_row = DetailLocator(
        children={".key": [DetailLocator("Ships from")], ".value": [DetailLocator("Acme")]}
    )
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
            ".seller-row": [seller_row],
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
    assert vendor["storefront_url"] == "/stores/acme"
    assert vendor["seller_info"] == {"Ships from": "Acme"}
    assert products[0].product_id == "ASIN1"
    assert products[0].title == "Catalog product"
    assert products[0].price == 10.0
