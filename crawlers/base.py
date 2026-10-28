from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from models import ProductItem, VendorRecord
from include.sanitization import LocalizedSanitization
from models.config import MarketplaceConfig


class BaseCrawler(ABC):
    """Abstract interface for marketplace-specific asynchronous crawlers."""

    def __init__(
        self, 
        marketplace_name: str, 
        version: str, 
        sanitizer: LocalizedSanitization,
        config: MarketplaceConfig
    ) -> None:
        """Store the injected marketplace metadata and parsing services."""
        self.marketplace_name = marketplace_name
        self.version = version
        self.sanitizer = sanitizer
        self.config = config

    def extract_vendor_id(self, vendor_url: str) -> Optional[str]:
        """Extract a vendor ID through the injected sanitizer."""
        try:
            return self.sanitizer.extract_vendor_id(vendor_url)
        except (TypeError, ValueError):
            return None
        
    @abstractmethod
    async def extract_search_items(self, search_term: str, limit: int = 50, sort_strategy: Optional[str] = None) -> AsyncIterator[ProductItem]:
        """Yield products from a marketplace search page.

        Args:
            search_term: Marketplace query string.
            limit: Maximum number of products to yield.
            sort_strategy: Optional marketplace-specific sort key.

        Yields:
            Marketplace product records.
        """
        pass

    @abstractmethod
    async def extract_vendor_info(self, vendor_url: str) -> dict:
        """Return raw vendor data extracted from a vendor page.

        Args:
            vendor_url: Vendor page URL.

        Returns:
            Marketplace-specific vendor fields as a dictionary.
        """
        pass