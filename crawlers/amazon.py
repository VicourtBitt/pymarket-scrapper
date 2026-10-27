from html.parser import HTMLParser
import logging
from enum import Enum
from typing import AsyncIterator, Optional
from urllib.parse import urlencode, urljoin

from playwright.async_api import Page

from include import LocalizedSanitization
from models import ProductItem, VendorProfile
from models.config import MarketplaceConfig
from crawlers import BaseCrawler


class _HtmlText(HTMLParser):
    """Convert configured HTML content to plain text without script/style content."""

    def __init__(self, value: str) -> None:
        super().__init__()
        self._ignored = 0
        self._parts: list[str] = []
        self.feed(value)
        self.text = " ".join("".join(self._parts).split()) or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in {"script", "style"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self._parts.append(data)


class AmazonSortFilter(Enum):
    """Compatibility names for configuration keys, not Amazon sort values."""
    BEST_SELLERS = "best_sellers"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    REVIEWS = "reviews"
    NEWEST = "newest"
    RELEVANCE = "relevance"


class AmazonCrawler(BaseCrawler):
    """Extract configured Amazon search, product, vendor, and catalog data."""

    _DEFAULT_BASE_URL = "https://www.amazon.com.br/"

    def __init__(self, page: Page, sanitizer: LocalizedSanitization, config: MarketplaceConfig) -> None:
        """Initialize the crawler with injected browser and marketplace services.

        Args:
            page: Playwright page used for all navigation and locator queries.
            sanitizer: Locale-aware parser for prices and marketplace IDs.
            config: Validated selectors and URL/query configuration.
        """
        super().__init__(
            marketplace_name=config.marketplace or "amazon",
            version="1.0.0",
            sanitizer=sanitizer,
            config=config,
        )
        self.page = page
        self.logger = logging.getLogger("pymarket_scrapper.crawlers.amazon")

    def _normalize_product_url(self, product_url: str) -> str:
        """Return an absolute product URL using the configured base URL."""
        return urljoin(self.config.base_url or self._DEFAULT_BASE_URL, product_url)

    async def extract_vendor_info(self, vendor_url: str) -> dict:
        """Extract configured seller identity, storefront, and seller fields.

        Args:
            vendor_url: Vendor page URL to navigate to.

        Returns:
            Raw vendor fields including ``vendor_url``, ``name``,
            ``storefront_url``, and ``seller_info``.
        """
        selectors = self.config.vendor_page
        await self.page.goto(vendor_url)

        storefront_url = None
        if selectors.storefront_href:
            storefront = self.page.locator(selectors.storefront_href).first
            if await storefront.count() > 0:
                storefront_url = await storefront.get_attribute("href")

        name = await self._optional_text(selectors.name)
        seller_info: dict[str, str] = {}
        if selectors.seller_info_row:
            rows = await self.page.locator(selectors.seller_info_row).all()
            for row in rows:
                key = await self._optional_text_from(row, selectors.seller_info_key)
                value = await self._optional_text_from(row, selectors.seller_info_value)
                if key and value:
                    seller_info[key] = value

        return {
            "vendor_url": vendor_url,
            "name": name,
            "storefront_url": storefront_url,
            "seller_info": seller_info,
        }

    async def extract_product_info(self, product_url: str) -> dict:
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
        await self.page.goto(normalized_product_url)
        title = await self._optional_text(selectors.title)
        price_text = await self._price_text(selectors)
        vendor_id = None
        vendor_url = None
        if selectors.merchant_vendor_id:
            merchant = self.page.locator(selectors.merchant_vendor_id).first
            if await merchant.count() > 0:
                vendor_id = await merchant.get_attribute("data-csa-c-asin")
                if selectors.merchant_vendor_link:
                    vendor_link = self.page.locator(selectors.merchant_vendor_link).first
                    if await vendor_link.count() > 0:
                        href = await vendor_link.get_attribute("href")
                        if href:
                            vendor_url = urljoin(normalized_product_url, href)

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
        return {
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

    async def extract_vendor_catalog(
        self, vendor_url: str, limit: int = 50
    ) -> AsyncIterator[ProductItem]:
        """Yield products listed on a configured vendor catalog page.

        Args:
            vendor_url: Catalog or storefront URL to navigate to.
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
        await self.page.goto(vendor_url)

        cards = await self.page.locator(selectors.product_card).all()
        for card in cards[:limit]:
            product_id = await card.get_attribute(
                selectors.product_id_attribute or "data-asin"
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
                url=url or vendor_url,
                price=self.sanitizer.parse_price(price_text or ""),
                currency=(
                    self.sanitizer.extract_currency_symbol(price_text or "")
                    or self.sanitizer.default_currency_fallback
                ),
                vendor_id=self.sanitizer.extract_vendor_id(vendor_url),
            )

    async def _optional_text(self, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        return await self._optional_text_from(self.page, selector)

    async def _optional_text_from(self, owner: object, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        locator = owner.locator(selector).first
        if await locator.count() == 0:
            return None
        value = (await locator.inner_text()).strip()
        return value or None

    async def _optional_attribute_from(
        self, owner: object, selector: Optional[str], attribute: str
    ) -> Optional[str]:
        if not selector:
            return None
        locator = owner.locator(selector).first
        if await locator.count() == 0:
            return None
        return await locator.get_attribute(attribute)

    async def _optional_html_text(self, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        locator = self.page.locator(selector).first
        if await locator.count() == 0:
            return None
        if hasattr(locator, "inner_html"):
            return _HtmlText(await locator.inner_html()).text
        return (await locator.inner_text()).strip() or None

    async def _all_text(self, selector: Optional[str]) -> list[str]:
        if not selector:
            return []
        return [
            value
            for value in [
                (await item.inner_text()).strip()
                for item in await self.page.locator(selector).all()
            ]
            if value
        ]

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

    async def extract_vendor_profile(self, vendor_url: str) -> AsyncIterator[VendorProfile]:
        """Retain the previous profile interface without emitting records.

        Args:
            vendor_url: Vendor URL recorded in the diagnostic log.

        Yields:
            No profiles; current workflow uses ``extract_vendor_info``.
        """
        self.logger.info("Extracting vendor profile from %s", vendor_url)
        if False:
            yield VendorProfile()

    async def extract_search_items(
        self, search_term: str, limit: int = 50,
        sort_strategy: Optional[str] = None
    ) -> AsyncIterator[ProductItem]:
        """Yield products from configured Amazon search result pages.

        Args:
            search_term: Marketplace search query.
            limit: Maximum number of eligible products to yield.
            sort_strategy: Configuration key or ``AmazonSortFilter`` value.

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
            sort_name = (
                sort_strategy.value
                if isinstance(sort_strategy, AmazonSortFilter)
                else str(sort_strategy).lower()
            )
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
                    product_id=product_id or "N/A",
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