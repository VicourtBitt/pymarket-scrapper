"""Configuration-driven Amazon product crawler (search and detail pages)."""

from typing import Any, AsyncIterator, Optional
from urllib.parse import urlencode, urljoin

from playwright.async_api import Page

from crawlers.base import BaseCrawler
from include import LocalizedSanitization
from models import ProductItem
from models.config import MarketplaceConfig


class AmazonCrawler(BaseCrawler):
    """Extract configured Amazon search results and product detail pages.

    Vendor profiles and storefront catalogs are handled by
    ``crawlers.amazon_vendor.AmazonVendorCrawler``.
    """

    def __init__(self, page: Page, sanitizer: LocalizedSanitization, config: MarketplaceConfig) -> None:
        super().__init__(page, sanitizer, config, "pymarket_scrapper.crawlers.amazon")

    def _normalize_product_url(self, product_url: str) -> str:
        """Return an absolute product URL using the configured base URL."""
        if not self.config.base_url:
            raise ValueError("Amazon marketplace configuration must define base_url")
        return urljoin(self.config.base_url, product_url)

    async def extract_product_info(self, product_url: str) -> dict[str, Any]:
        """Extract configured product details from an Amazon product page.

        Args:
            product_url: Relative or absolute product URL.

        Returns:
            Raw detail fields normalized for the workflow, including price,
            vendor, description, features, and reviews.

        Raises:
            ValueError: If ``product_page`` is absent from the configuration.
        """
        selectors = self.config.product_page
        if selectors is None:
            raise ValueError("Amazon marketplace configuration must define product_page")

        normalized_product_url = self._normalize_product_url(product_url)
        self.logger.info("product detail starts url=%s", normalized_product_url)
        await self.page.goto(normalized_product_url)
        title = await self._optional_text(selectors.title)
        price_text = await self._price_text(selectors)
        vendor_id = None
        vendor_url = None
        if selectors.merchant_vendor_link:
            vendor_link = self.page.locator(selectors.merchant_vendor_link).first
            if await vendor_link.count() > 0:
                href = await vendor_link.get_attribute("href")
                if href:
                    resolved_vendor_url = urljoin(normalized_product_url, href)
                    if self._is_navigable_http_url(resolved_vendor_url):
                        vendor_url = resolved_vendor_url
                        vendor_id = self.extract_vendor_id(vendor_url)
                    else:
                        self.logger.debug(
                            "Ignoring non-navigable Amazon merchant URL: %s",
                            resolved_vendor_url,
                        )

        # Retain support for configurations that expose only the merchant
        # element's legacy data attribute.
        if (
            not vendor_id
            and selectors.merchant_vendor_id
            and selectors.merchant_vendor_id_attribute
        ):
            merchant = self.page.locator(selectors.merchant_vendor_id).first
            if await merchant.count() > 0:
                vendor_id = await merchant.get_attribute(
                    selectors.merchant_vendor_id_attribute
                )

        details: dict[str, str] = {}
        if selectors.details_row:
            rows = await self.page.locator(selectors.details_row).all()
            for row in rows:
                cells = await row.locator(selectors.details_cell or "td").all()
                if len(cells) >= 2:
                    key = (await cells[0].inner_text()).strip()
                    value = (await cells[1].inner_text()).strip()
                    if key:
                        details[key] = value

        description = await self._optional_html_text(selectors.description)
        features = await self._all_text(selectors.features)
        reviews = await self._extract_reviews(selectors.reviews)
        result = {
            "url": normalized_product_url,
            "title": title,
            "price": self.sanitizer.parse_price(price_text),
            "currency": (
                self.sanitizer.extract_currency_symbol(price_text)
                or self.sanitizer.default_currency_fallback
            ),
            "vendor_id": vendor_id,
            "vendor_url": vendor_url,
            "details": details,
            "description": description,
            "features": features,
            "reviews": reviews,
        }
        self.logger.info(
            "product detail completes url=%s vendor_id_present=%s vendor_url_present=%s",
            normalized_product_url,
            bool(vendor_id),
            bool(vendor_url),
        )
        self.logger.info(
            "extracted vendor fields vendor_id=%s vendor_url=%s",
            vendor_id,
            vendor_url,
        )
        return result

    async def _extract_reviews(self, selectors: object) -> list[dict[str, str]]:
        if selectors is None or not getattr(selectors, "review_card", None):
            return []
        reviews = []
        for card in await self.page.locator(selectors.review_card).all():
            review: dict[str, str] = {}
            for field in ("title", "rating", "text"):
                value = await self._optional_text_from(card, getattr(selectors, field, None))
                if value:
                    review[field] = value
            if review:
                reviews.append(review)
        return reviews

    async def _price_text(self, selectors: object) -> str:
        parts = []
        for selector_name in ("price_whole", "price_decimal", "price_fraction"):
            selector = getattr(selectors, selector_name, None)
            value = await self._optional_text(selector)
            if value:
                parts.append(value)
        if parts:
            return "".join(parts)
        return (await self._optional_text(getattr(selectors, "price", None))) or ""

    async def extract_search_items(
        self, search_term: str, limit: int = 50,
        sort_strategy: Optional[str] = None
    ) -> AsyncIterator[ProductItem]:
        """Yield products from configured Amazon search result pages.

        Args:
            search_term: Marketplace search query.
            limit: Maximum number of eligible products to yield.
            sort_strategy: A ``query_parameters.sort_values`` key.

        Yields:
            Product records with normalized URLs, prices, currencies, and IDs.

        Raises:
            ValueError: If the base URL or requested sort is not configured.
        """
        self.logger.info(f"Initializing the extraction of {search_term} from Amazon")

        if not self.config.base_url:
            raise ValueError("Amazon marketplace configuration must define base_url")
        query = {self.config.query_parameters.search_key: search_term}
        if sort_strategy:
            sort_name = str(sort_strategy).lower()
            configured_sort = getattr(self.config.query_parameters.sort_values, sort_name, None)
            if configured_sort is None:
                raise ValueError(f"Sort filter is not configured: {sort_name}")
            query[self.config.query_parameters.sort_key] = configured_sort
            self.logger.info("Applying sort filter: %s", sort_name)
        search_url = f"{self.config.base_url.rstrip('/')}?{urlencode(query)}"

        # Going into our search page
        await self.page.goto(search_url)
        items_found: int = 0
        while items_found < limit:
            selectors = self.config.search_page
            try:
                await self.page.wait_for_selector(selectors.product_card)
            except Exception as exc:
                self.logger.warning("Product cards unavailable: %s", exc)
                break

            # Extract the items/eligible products that have been loaded
            products = await self.page.locator(selectors.product_card).all()
            if not products:
                self.logger.info("No more products in that page.")
                break

            for card in products:
                if items_found >= limit:
                    self.logger.info("The limit has been achieved. Breaking the extraction loop.")
                    break

                sponsored_tag = card.locator(selectors.sponsored_ad_tag).first
                if await sponsored_tag.count() > 0:
                    self.logger.info(f"Skipping sponsored/advertising product.")
                    continue

                try:
                    title_element = card.locator(selectors.title).first
                    title = await title_element.inner_text()

                    link_element = card.locator(selectors.url).first
                    url_path = await link_element.get_attribute("href")

                    product_id = await card.get_attribute(selectors.id_attribute)
                    if not product_id:
                        self.logger.warning(
                            "Skipping search card without %s", selectors.id_attribute
                        )
                        continue

                    price = 0.0
                    currency = None
                    price_element = card.locator(selectors.price).first

                    if await price_element.count() > 0:
                        price_text = await price_element.inner_text()
                        currency = self.sanitizer.extract_currency_symbol(price_text)
                        price = self.sanitizer.parse_price(price_text)

                except Exception as e:
                    self.logger.exception(
                        "Exception while extracting %s", search_term
                    )
                    continue

                product = ProductItem(
                    product_id=product_id,
                    title=title,
                    url=(self._normalize_product_url(url_path) if url_path else None),
                    price=price,
                    currency=currency or self.sanitizer.default_currency_fallback,
                    vendor_id=None
                )

                yield product
                items_found += 1

            if items_found < limit:
                next_button = self.page.locator(selectors.next_page_button).first
                if await next_button.count() > 0 and await next_button.is_visible():
                    self.logger.info("Navigating to next page...")
                    await next_button.click()
                    await self.page.wait_for_timeout(2000)
                else:
                    break