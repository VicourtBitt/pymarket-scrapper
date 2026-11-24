from crawlers.base import BaseCrawler, BaseVendorCrawler
from crawlers.amazon import AmazonCrawler
from crawlers.amazon_vendor import AmazonVendorCrawler
from crawlers.mercado_libre import MercadoLibreCrawler, MercadoLibreVendorCrawler
from crawlers.registry import CrawlerClasses, crawler_classes, register_marketplace
