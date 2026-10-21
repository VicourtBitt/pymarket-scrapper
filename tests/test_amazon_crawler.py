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
