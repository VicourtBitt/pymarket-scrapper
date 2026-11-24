from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any

class ProductItem(BaseModel):
    """ The product that'll be extracted from the search page """
    product_id: str = Field(alias="product_id")
    title: str = Field(alias="title")
    url: Optional[HttpUrl|str] = Field(alias="url")
    price: float = Field(alias="price")
    currency: str = Field(alias="currency")
    vendor_id: Optional[str] = Field(alias="vendor_id")

    external_id : Optional[str] = Field(
        default=None,
        alias="external_id",
        description="External ID"
    )

    metadata: Optional[Dict[str, Any]] = Field(alias="metadata", default_factory=dict)