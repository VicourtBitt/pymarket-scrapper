"""Configuration-driven Amazon vendor crawler (seller profile and storefront)."""

from typing import Any, AsyncIterator
from urllib.parse import urljoin

from playwright.async_api import Page

from crawlers.base import BaseVendorCrawler
from include import LocalizedSanitization
from models import ProductItem
from models.config import MarketplaceConfig


class AmazonVendorCrawler(BaseVendorCrawler):
    """Extract Amazon seller identity, seller-info rows and storefront products."""

    def __init__(self, page: Page, sanitizer: LocalizedSanitization, config: MarketplaceConfig) -> None:
        super().__init__(
            page, sanitizer, config, "pymarket_scrapper.crawlers.amazon.vendor"
        )

    async def extract_vendor_info(self, vendor_url: str) -> dict[str, Any]:
        """Extract configured seller identity, storefront, and seller fields.

        Args:
            vendor_url: Vendor page URL to navigate to.

        Returns:
            Raw vendor fields including ``vendor_url``, ``name``,
            ``storefront_url``, and ``seller_info``.
        """
        selectors = self.config.vendor_page
        self.logger.info("vendor extraction starts url=%s", vendor_url)
        await self._goto_dom_ready(vendor_url)

        storefront_url = None
        for storefront_selector in self._selector_alternatives(selectors.storefront_href):
            self.logger.debug(
                "storefront selector inspected selector=%s", storefront_selector
            )
            try:
                storefront = self.page.locator(storefront_selector).first
                if await storefront.count() == 0:
                    self.logger.debug(
                        "storefront selector href result selector=%s found=false",
                        storefront_selector,
                    )
                    continue
                href = await storefront.get_attribute("href")
                if not href:
                    self.logger.debug(
                        "storefront selector href result selector=%s found=true href_present=false",
                        storefront_selector,
                    )
                    continue
                candidate = urljoin(vendor_url, href.strip())
                self.logger.debug(
                    "storefront selector href result selector=%s found=true "
                    "href_present=true href=%s",
                    storefront_selector,
                    candidate,
                )
                if self._is_navigable_http_url(candidate):
                    storefront_url = candidate
                    break
                self.logger.debug(
                    "Ignoring non-navigable Amazon storefront URL from %s: %s",
                    storefront_selector,
                    candidate,
                )
            except Exception as exc:
                # A stale or malformed optional selector must not prevent the
                # seller identity and other seller fields from being extracted.
                self.logger.warning(
                    "Unable to inspect Amazon storefront selector %s: %s",
                    storefront_selector,
                    exc,
                )

        name = await self._optional_text(selectors.name)
        seller_info: dict[str, str] = {}
        if selectors.seller_info_row:
            rows = await self.page.locator(selectors.seller_info_row).all()
            self.logger.info("seller rows count=%d", len(rows))
            for row in rows:
                key = await self._optional_text_from(row, selectors.seller_info_key)
                value = await self._optional_text_from(row, selectors.seller_info_value)
                self.logger.debug(
                    "seller row extracted key_present=%s value_present=%s",
                    bool(key),
                    bool(value),
                )
                if key and value:
                    seller_info[key] = value

        result = {
            "vendor_url": vendor_url,
            "name": name,
            "storefront_url": storefront_url,
            "seller_info": seller_info,
        }
        self.logger.info(
            "vendor extraction completes url=%s storefront_present=%s seller_fields=%d",
            vendor_url,
            bool(storefront_url),
            len(seller_info),
        )
        return result

    async def extract_vendor_catalog(
        self, catalog_url: str, limit: int = 50
    ) -> AsyncIterator[ProductItem]:
        """Yield products listed on a configured vendor catalog page.

        Args:
            catalog_url: Catalog or storefront URL to navigate to.
            limit: Maximum number of catalog cards to inspect.

        Yields:
            Product records parsed from configured catalog cards.

        Raises:
            ValueError: If the catalog page or product-card selector is absent.
        """
        selectors = self.config.vendor_catalog_page
        if selectors is None or not selectors.product_card:
            raise ValueError(
                "Amazon marketplace configuration must define vendor_catalog_page"
            )
        self.logger.info("catalog extraction starts url=%s", catalog_url)
        await self._goto_dom_ready(catalog_url)

        cards = await self.page.locator(selectors.product_card).all()
        self.logger.info("catalog extraction cards=%d", min(len(cards), limit))
        for card in cards[:limit]:
            product_id = await card.get_attribute(
                selectors.product_id_attribute or self.config.search_page.id_attribute
            )
            if not product_id:
                self.logger.warning("Skipping vendor catalog card without product ID")
                continue

            title = await self._optional_text_from(card, self.config.search_page.title)
            url = await self._optional_attribute_from(
                card, self.config.search_page.url, "href"
            )
            price_text = await self._optional_text_from(card, self.config.search_page.price)
            yield ProductItem(
                product_id=product_id,
                title=title or product_id,
                url=url or catalog_url,
                price=self.sanitizer.parse_price(price_text or ""),
                currency=(
                    self.sanitizer.extract_currency_symbol(price_text or "")
                    or self.sanitizer.default_currency_fallback
                ),
                vendor_id=self.extract_vendor_id(catalog_url),
            )
