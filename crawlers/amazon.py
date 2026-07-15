from typing import Iterator
from models import VendorProfile, ProductItem
from crawlers import BaseCrawler

class AmazonCrawler(BaseCrawler):
    """ The crawler implementation for the Amazon website. """

    def extract_vendor_profile(self, vendor_url: str) -> VendorProfile:
        pass