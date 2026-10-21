from pydantic import BaseModel, ConfigDict
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

    def as_sql(self) -> tuple[str, list[str]]:
        if self.title_contains is None:
            return "TRUE", []
        return "title ILIKE ?", [f"%{self.title_contains}%"]

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
    name: str
    rating: Optional[str] = None
    contact_info: Optional[str] = None

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

    @classmethod
    def from_marketplace(
        cls, marketplace: str, configs_dir: Path
    ) -> "MarketplaceConfig":
        """Load ``<marketplace>.yml`` from an explicitly supplied directory."""
        from models.config_reader import MarketplaceConfigFactory

        return MarketplaceConfigFactory.from_marketplace(
            marketplace=marketplace, configs_dir=configs_dir
        )