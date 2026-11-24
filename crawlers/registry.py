"""Factory mapping a marketplace family to its crawler classes."""

from typing import NamedTuple

from crawlers.amazon import AmazonCrawler
from crawlers.amazon_vendor import AmazonVendorCrawler
from crawlers.base import BaseCrawler, BaseVendorCrawler
from crawlers.mercado_libre import MercadoLibreCrawler, MercadoLibreVendorCrawler
from models.config import MarketplaceConfig


class CrawlerClasses(NamedTuple):
    crawler: type[BaseCrawler]
    vendor_crawler: type[BaseVendorCrawler]


_REGISTRY: dict[str, CrawlerClasses] = {}


def register_marketplace(
    name: str,
    crawler: type[BaseCrawler],
    vendor_crawler: type[BaseVendorCrawler],
) -> None:
    """Register (or replace) the crawler pair for a marketplace family."""
    _REGISTRY[name.casefold()] = CrawlerClasses(crawler, vendor_crawler)


def crawler_classes(config: MarketplaceConfig, marketplace: str) -> CrawlerClasses:
    """Return the crawler pair for a configuration.

    The YAML ``marketplace`` key selects the family, so several configuration
    files (for example ``amazon_br.yml`` and ``amazon_us.yml``) can share one
    implementation. The configuration file key is the fallback.
    """
    family = (config.marketplace or marketplace).casefold()
    try:
        return _REGISTRY[family]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise ValueError(
            f"No crawler registered for marketplace {family!r} (known: {known})"
        ) from None


register_marketplace("amazon", AmazonCrawler, AmazonVendorCrawler)
register_marketplace("mercado_libre", MercadoLibreCrawler, MercadoLibreVendorCrawler)
