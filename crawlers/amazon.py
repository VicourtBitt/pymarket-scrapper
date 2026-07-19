from typing import AsyncIterator
from playwright.async_api import Page
from models import VendorProfile, ProductItem
from crawlers import BaseCrawler
import logging

class AmazonCrawler(BaseCrawler):
    """ The crawler implementation for the Amazon website. """

    def __init__(self, marketplace_name: str, version: str, page: Page, base_url: str) -> None:
        """ Initialize the crawler with an initial page.
        The base_url param should have the specific localization identification in the domain, such as .br
        for Brazil, .de for Germany and so on.
        """
        super().__init__(marketplace_name, version)
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
            await self.page.wait_for_selector("span[data-component-type='s-search-result']")

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

                    ...
                except Exception as e:
                    self.logger.error(f"Exception while extracting {search_term}: {e}")
                    continue

        pass