from pydantic import BaseModel, ConfigDict, Field
from pathlib import Path
from typing import Optional

class SortValues(BaseModel):
    # Allow extra fields in case other marketplaces have different sorting concepts
    model_config = ConfigDict(extra='allow')
    
    best_sellers: Optional[str] = None
    price_asc: Optional[str] = None
    price_desc: Optional[str] = None
    reviews: Optional[str] = None
    newest: Optional[str] = None
    relevance: Optional[str] = None

class QueryParameters(BaseModel):
    model_config = ConfigDict(extra='allow')
    search_key: str
    sort_key: str
    sort_values: SortValues


class ProductFilter(BaseModel):
    """Validated product-job filter; intentionally not an arbitrary SQL fragment."""

    title_contains: Optional[str] = None

    def matches(self, title: Optional[str]) -> bool:
        """Return whether a product title satisfies this configured filter."""
        if self.title_contains is None:
            return True
        if title is None:
            return False
        return self.title_contains.casefold() in title.casefold()

    def as_sql(self) -> tuple[str, list[str]]:
        """Return a parameterized clause matching ``matches()`` semantics.

        ``%``, ``_`` and ``\\`` in the value are escaped so they match
        literally, as in the in-memory filter.
        """
        if self.title_contains is None:
            return "TRUE", []
        escaped = (
            self.title_contains.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        return "title ILIKE ? ESCAPE '\\'", [f"%{escaped}%"]

class SearchPageSelectors(BaseModel):
    model_config = ConfigDict(extra='allow')
    product_card: str
    sponsored_ad_tag: str
    title: str
    url: str
    price: str
    id_attribute: str
    next_page_button: str
    vendor_url: Optional[str] = None

class VendorPageSelectors(BaseModel):
    model_config = ConfigDict(extra='allow')
    name: Optional[str] = None
    rating: Optional[str] = None
    contact_info: Optional[str] = None
    storefront_href: Optional[str] = None
    seller_info_row: Optional[str] = None
    seller_info_key: Optional[str] = None
    seller_info_value: Optional[str] = None


class ProductPageSelectors(BaseModel):
    """Optional selectors used when a product detail page is configured."""

    model_config = ConfigDict(extra="allow")

    title: Optional[str] = None
    price: Optional[str] = None
    price_whole: Optional[str] = None
    price_decimal: Optional[str] = None
    price_fraction: Optional[str] = None
    merchant_vendor_id: Optional[str] = None
    merchant_vendor_id_attribute: Optional[str] = None
    merchant_vendor_link: Optional[str] = None
    details_row: Optional[str] = None
    details_cell: Optional[str] = None
    description: Optional[str] = None
    features: Optional[str] = None
    reviews: Optional["ReviewPageSelectors"] = None


class ReviewPageSelectors(BaseModel):
    """Optional selectors for the review section of a product page."""

    model_config = ConfigDict(extra="allow")

    review_card: Optional[str] = None
    title: Optional[str] = None
    rating: Optional[str] = None
    text: Optional[str] = None


class VendorCatalogPageSelectors(BaseModel):
    """Optional selectors used when crawling a vendor's product catalog."""

    model_config = ConfigDict(extra="allow")

    product_card: Optional[str] = None
    product_id_attribute: Optional[str] = None

class LocaleSettings(BaseModel):
    """Number and currency conventions used by ``LocalizedSanitization``."""

    decimal_separator: str = "."
    thousands_separator: str = ","
    currency_fallback: str = ""


class BrowserSettings(BaseModel):
    """Playwright browser-context settings for one marketplace."""

    user_agent: Optional[str] = None
    viewport_width: int = 1280
    viewport_height: int = 720
    locale: Optional[str] = None

    def context_options(self) -> dict:
        """Keyword arguments for ``Browser.new_context``."""
        options: dict = {
            "viewport": {"width": self.viewport_width, "height": self.viewport_height}
        }
        if self.user_agent:
            options["user_agent"] = self.user_agent
        if self.locale:
            options["locale"] = self.locale
        return options


class MarketplaceConfig(BaseModel):
    """
    The master configuration model for any marketplace.
    Validates the JSON configuration file perfectly.
    """
    # These fields have defaults so existing configuration files remain valid.
    marketplace: Optional[str] = None
    base_url: Optional[str] = None
    query_parameters: QueryParameters
    search_page: SearchPageSelectors
    vendor_page: VendorPageSelectors
    product_page: Optional[ProductPageSelectors] = None
    vendor_catalog_page: Optional[VendorCatalogPageSelectors] = None
    locale: LocaleSettings = Field(default_factory=LocaleSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)

    @classmethod
    def from_marketplace(
        cls, marketplace: str, configs_dir: Path
    ) -> "MarketplaceConfig":
        """Load ``<marketplace>.yml`` from an explicitly supplied directory."""
        from models.config_reader import MarketplaceConfigFactory

        return MarketplaceConfigFactory.from_marketplace(
            marketplace=marketplace, configs_dir=configs_dir
        )