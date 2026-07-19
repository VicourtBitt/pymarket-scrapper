from abc import ABC, abstractmethod
from typing import AsyncIterator
from models import VendorProfile, ProductItem

class BaseCrawler(ABC):
    """ The abstract interface that most specialized crawlers must follow. """
    def __init__(self, marketplace_name, version):
        self.marketplace_name = marketplace_name
        self.version = version

    @abstractmethod
    async def extract_search_items(self, search_term: str, limit: int = 50) -> AsyncIterator[ProductItem]:
        """ Crawls a search page and return items one by one using YIELD """
        pass

    @abstractmethod
    async def extract_vendor_profile(self, vendor_url: str) -> AsyncIterator[VendorProfile]:
        """ Crawls the vendor page and return their details. """
        pass