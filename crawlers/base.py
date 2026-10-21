from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from models import ProductItem, VendorRecord
from include.sanitization import LocalizedSanitization
from models.config import MarketplaceConfig

class BaseCrawler(ABC):
    """
    The abstract interface that all specialized crawlers must follow.
    Now requires a configuration object.
    """
    
    def __init__(
        self, 
        marketplace_name: str, 
        version: str, 
        sanitizer: LocalizedSanitization,
        config: MarketplaceConfig
    ):
        self.marketplace_name = marketplace_name
        self.version = version
        self.sanitizer = sanitizer
        self.config = config
        
    @abstractmethod
    async def extract_search_items(self, search_term: str, limit: int = 50, sort_strategy: Optional[str] = None) -> AsyncIterator[ProductItem]:
        """
        Crawls a search page and YIELDS products asynchronously.
        """
        pass

    @abstractmethod
    async def extract_vendor_info(self, vendor_url: str) -> dict:
        """
        Crawls a specific vendor's page and returns their raw dictionary data.
        """
        pass