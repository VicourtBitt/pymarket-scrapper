from typing import Iterator
from models import VendorProfile, ProductItem
from crawlers import BaseCrawler

class MercadoLibre(BaseCrawler):
    """ The crawler implementation for the Mercado Libre website. """

    def extract_vendor_profile(self, vendor_url: str) -> VendorProfile:
        pass