from typing import AsyncIterator, Optional
from urllib.parse import urlencode
from playwright.async_api import Page
from models import VendorProfile, ProductItem
from include import LocalizedSanitization
from crawlers import BaseCrawler
import logging
from enum import Enum
from models.config import MarketplaceConfig

class AmazonSortFilter(Enum):
    """Compatibility names for configuration keys, not Amazon sort values."""
    BEST_SELLERS = "best_sellers"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    REVIEWS = "reviews"
    NEWEST = "newest"
    RELEVANCE = "relevance"

class AmazonCrawler(BaseCrawler):
    """ The crawler implementation for the Amazon website. """

    def __init__(self, page: Page, sanitizer: LocalizedSanitization, config: MarketplaceConfig) -> None:
        """Initialize the crawler with injected Playwright and marketplace config."""
        super().__init__(
            marketplace_name=config.marketplace or "amazon",
            version="1.0.0",
            sanitizer=sanitizer,
            config=config,
        )
        self.page = page
        self.logger = logging.getLogger("pymarket_scrapper.crawlers.amazon")

    async def extract_vendor_info(self, vendor_url: str) -> dict:
        """Vendor extraction is a separate roadmap component."""
        raise NotImplementedError(
            "Amazon vendor extraction requires AmazonVendorCrawler; "
            "search crawling does not provide vendor data"
        )

    async def extract_vendor_profile(self, vendor_url: str) -> AsyncIterator[VendorProfile]:
        """Compatibility interface for callers of the previous API."""
        self.logger.info("Extracting vendor profile from %s", vendor_url)
        if False:
            yield VendorProfile()

    async def extract_search_items(
        self, search_term: str, limit: int = 50,
        sort_strategy: Optional[str] = None
    ) -> AsyncIterator[ProductItem]:
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
                    url=url_path,
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