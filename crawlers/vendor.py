"""Marketplace vendor-page crawler interfaces and implementations."""

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from urllib.parse import urlsplit

from playwright.async_api import Page

from include import LocalizedSanitization
from models import VendorProfile
from models.config import MarketplaceConfig


class BaseVendorCrawler(ABC):
    """Extract vendor profiles independently from product search crawling."""

    def __init__(
        self, page: Page, sanitizer: LocalizedSanitization,
        config: MarketplaceConfig,
    ) -> None:
        self.page = page
        self.sanitizer = sanitizer
        self.config = config

    @abstractmethod
    async def extract_profile(self, vendor_url: str) -> AsyncIterator[VendorProfile]:
        """Yield the profile found at ``vendor_url``."""
        raise NotImplementedError


class AmazonVendorCrawler(BaseVendorCrawler):
    """Placeholder for the future, configuration-driven vendor extractor.

    Vendor extraction and persistence are intentionally deferred until the
    vendor model and external-link contract are finalized.
    """

    def __init__(
        self, page: Page, sanitizer: LocalizedSanitization,
        config: MarketplaceConfig,
    ) -> None:
        super().__init__(page, sanitizer, config)
        self.logger = logging.getLogger("pymarket_scrapper.crawlers.vendor")

    async def _optional_text(self, selector: Optional[str]) -> Optional[str]:
        if not selector:
            return None
        try:
            locator = self.page.locator(selector).first
            if await locator.count() == 0:
                return None
            value = (await locator.inner_text()).strip()
            return value or None
        except Exception:
            self.logger.warning("Optional vendor selector failed: %s", selector)
            return None

    async def extract_profile(self, vendor_url: str) -> AsyncIterator[VendorProfile]:
        raise NotImplementedError(
            "Vendor extraction is intentionally deferred until the vendor "
            "model and external-link contract are finalized."
        )
        if False:
            yield VendorProfile(vendor_id="", name="")
