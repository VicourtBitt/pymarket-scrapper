from typing import AsyncIterator
from playwright.async_api import Page
from models import VendorProfile, ProductItem
from include import LocalizedSanitization
from crawlers import BaseCrawler
import logging
import re

class AmazonCrawler(BaseCrawler):
    """ The crawler implementation for the Amazon website. """

    def __init__(self, page: Page, base_url: str, sanitizer: LocalizedSanitization) -> None:
        """ Initialize the crawler with an initial page.
        The base_url param should have the specific localization identification in the domain, such as .br
        for Brazil, .de for Germany and so on.
        """
        super().__init__(marketplace_name="Amazon", version="1.0.0", sanitizer=sanitizer)
        self.page = page
        self.base_url = base_url
        self.logger = logging.getLogger("AmazonCrawler")

    async def extract_vendor_profile(self, vendor_url: str) -> AsyncIterator[VendorProfile]:
        pass

    async def extract_search_items(self, search_term: str, limit: int = 50) -> AsyncIterator[ProductItem]:
        self.logger.info(f"Initializing the extraction of {search_term} from Amazon")

        # Going into our search page
        await self.page.goto(f"{self.base_url}/s?k={search_term}")
        items_found: int = 0
        while items_found < limit:
            await self.page.wait_for_selector("div[data-component-type='s-search-result']")

            # Extract the items/eligible products that have been loaded
            products = await self.page.locator("div[data-component-type='s-search-result']").all()
            if not products:
                self.logger.info("No more products in that page.")
                break

            for card in products:
                if items_found >= limit:
                    self.logger.info("The limit has been achieved. Breaking the extraction loop.")
                    break

                try:
                    title_element = card.locator("a h2 span").first
                    title = await title_element.inner_text()

                    link_element = card.locator("div div a").first
                    url_path = await link_element.get_attribute("href")

                    product_id = await card.get_attribute("data-asin")

                    price = 0.0
                    currency = None
                    price_element = card.locator(".a-price .a-offscreen").first

                    if await price_element.count() > 0:
                        price_text = await price_element.inner_text()
                        currency = self.sanitizer.extract_currency_symbol(price_text)
                        price = self.sanitizer.parse_price(price_text)

                except Exception as e:
                    print(f"Exception while extracting {search_term}: {e}")
                    continue

                product = ProductItem(
                    product_id=product_id or "N/A",
                    title=title,
                    product_url=url_path,
                    price=price,
                    currency=currency,
                    vendor="PENDING"
                )

                yield product
                items_found += 1

            if items_found < limit:
                next_button = self.page.locator("a.s-pagination-next").first
                if await next_button.count() > 0 and await next_button.is_visible():
                    self.logger.info("Navigating to next page...")
                    await next_button.click()
                    await self.page.wait_for_timeout(2000)
                else:
                    break