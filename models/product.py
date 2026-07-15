from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any

class ProductItem(BaseModel):
    """ The product that'll be extracted from the search page """
    product_id: str = Field(alias="product_id")
    name: str = Field(alias="name")
    product_url: HttpUrl = Field(alias="product_url")
    price: float = Field(alias="price")
    currency: str = Field(alias="currency")
    vendor: str = Field(alias="vendor")

    external_id : Optional[str] = Field(
        default=None,
        alias="external_id",
        description="External ID"
    )

    metadata: Dict[str, Any] = Field(alias="metadata", default_factory=dict)