"""Mercado Libre crawler placeholders.

These classes satisfy the crawler contracts so the marketplace can be
registered and wired, but extraction is not implemented yet. A
``configs/mercado_libre.yml`` is also required before they can run.
"""

from typing import Any, AsyncIterator, Optional

from crawlers.base import BaseCrawler, BaseVendorCrawler
from models import ProductItem

_NOT_IMPLEMENTED = "Mercado Libre extraction is not implemented yet"


class MercadoLibreCrawler(BaseCrawler):
    """Product crawler for Mercado Libre (not implemented)."""

    async def extract_search_items(
        self, search_term: str, limit: int = 50, sort_strategy: Optional[str] = None
    ) -> AsyncIterator[ProductItem]:
        raise NotImplementedError(_NOT_IMPLEMENTED)
        yield  # pragma: no cover - makes this an async generator

    async def extract_product_info(self, product_url: str) -> dict[str, Any]:
        raise NotImplementedError(_NOT_IMPLEMENTED)


class MercadoLibreVendorCrawler(BaseVendorCrawler):
    """Vendor crawler for Mercado Libre (not implemented)."""

    async def extract_vendor_info(self, vendor_url: str) -> dict[str, Any]:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    async def extract_vendor_catalog(
        self, catalog_url: str, limit: int = 50
    ) -> AsyncIterator[ProductItem]:
        raise NotImplementedError(_NOT_IMPLEMENTED)
        yield  # pragma: no cover - makes this an async generator
