from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, Dict, Any

class VendorProfile(BaseModel):
    """ The Vendor profile model """
    vendor_id: str = Field(..., description="Vendor ID")
    name: str = Field(..., description="Vendor name")