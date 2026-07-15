from abc import ABC, abstractmethod
from typing import Iterator
from models import VendorProfile, ProductItem

class BaseCrawler(ABC):
    """ The abstract interface that most specialized crawlers must follow. """

    @abstractmethod
    def extract_search_items(self, search_term: str, limit: int = 50) -> Iterator[ProductItem]:
        """ Crawls a search page and return items one by one using YIELD """
        pass

    @abstractmethod
    def extract_vendor_profile(self, vendor_url: str) -> Iterator[VendorProfile]:
        """ Crawls the vendor page and return their details. """
        pass