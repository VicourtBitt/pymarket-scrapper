from sqlalchemy import Column, String, Float, JSON, ForeignKey
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class VendorRecord(Base):
    __tablename__ = "vendors"

    vendor_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    url = Column(String)
    extracted_phones = Column(JSON, default=True)
    extracted_emails = Column(JSON, default=True)
    external_id = Column(String, nullable=False, index=True)
    metadata_blob = Column(JSON, default={})


class ProductRecord(Base):
    __tablename__ = "products"

    product_id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    url = Column(String, nullable=True)
    price = Column(Float, nullable=True)
    vendor_id = Column(String, ForeignKey("vendors.vendor_id"), nullable=True)
    metadata_blob = Column(JSON, default={})