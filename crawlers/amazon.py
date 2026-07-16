from typing import AsyncIterator
from models import VendorProfile, ProductItem
from crawlers import BaseCrawler

class AmazonCrawler(BaseCrawler):
    """ The crawler implementation for the Amazon website. """

    async def extract_vendor_profile(self, vendor_url: str) -> AsyncIterator[VendorProfile]:
        pass

    async def extract_search_items(self, search_term: str, limit: int = 50) -> AsyncIterator[ProductItem]:
        pass