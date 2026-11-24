"""Marketplace-agnostic crawler contracts.

Product crawling (search + detail pages) and vendor crawling (seller profile +
storefront catalog) are separate responsibilities with separate classes. Both
receive the same injected page, sanitizer and configuration.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from playwright.async_api import Page

from crawlers.page import PageHelpers
from include.sanitization import LocalizedSanitization
from models import ProductItem
from models.config import MarketplaceConfig


class _ConfiguredCrawler(PageHelpers):
    """Shared constructor for crawlers driven by one marketplace configuration."""

    def __init__(
        self,
        page: Page,
        sanitizer: LocalizedSanitization,
        config: MarketplaceConfig,
        logger_name: Optional[str] = None,
    ) -> None:
        self.page = page
        self.sanitizer = sanitizer
        self.config = config
        self.marketplace_name = config.marketplace
        self.logger = logging.getLogger(
            logger_name or f"pymarket_scrapper.crawlers.{type(self).__name__}"
        )

    def extract_vendor_id(self, vendor_url: str) -> Optional[str]:
        """Extract a vendor ID through the injected sanitizer."""
        try:
            return self.sanitizer.extract_vendor_id(vendor_url)
        except (TypeError, ValueError):
            return None


class BaseCrawler(_ConfiguredCrawler, ABC):
    """Extract products from marketplace search and product detail pages."""

    @abstractmethod
    def extract_search_items(
        self, search_term: str, limit: int = 50, sort_strategy: Optional[str] = None
    ) -> AsyncIterator[ProductItem]:
        """Yield products from a marketplace search page.

        Args:
            search_term: Marketplace query string.
            limit: Maximum number of products to yield.
            sort_strategy: Optional ``query_parameters.sort_values`` key.
        """

    @abstractmethod
    async def extract_product_info(self, product_url: str) -> dict[str, Any]:
        """Return raw detail fields (including ``vendor_id``/``vendor_url``)."""


class BaseVendorCrawler(_ConfiguredCrawler, ABC):
    """Extract seller profiles and seller storefront catalogs."""

    @abstractmethod
    async def extract_vendor_info(self, vendor_url: str) -> dict[str, Any]:
        """Return raw vendor fields: ``vendor_url``, ``name``,
        ``storefront_url`` and ``seller_info``."""

    @abstractmethod
    def extract_vendor_catalog(
        self, catalog_url: str, limit: int = 50
    ) -> AsyncIterator[ProductItem]:
        """Yield products listed on a vendor storefront page."""
