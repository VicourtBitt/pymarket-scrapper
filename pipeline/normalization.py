"""Turn raw crawler dictionaries into the sink's product and vendor contracts."""

import logging
from typing import Any, Optional

from models import ProductItem

logger = logging.getLogger("pymarket_scrapper.pipeline.normalization")

_NAME_KEYS = {
    "name", "nome", "legal name", "nome legal", "business name",
    "nome comercial", "razão social",
}


def _normalized_key(key: str) -> str:
    return " ".join(
        key.casefold().replace("-", " ").replace("_", " ").split()
    ).rstrip(":").strip()


def seller_info_name(seller_info: Any) -> Optional[str]:
    """Return a meaningful name or legal-name value from seller info."""
    if not isinstance(seller_info, dict):
        return None
    for key, value in seller_info.items():
        if not isinstance(key, str) or value is None:
            continue
        candidate = str(value).strip()
        if not candidate:
            continue
        normalized_key = _normalized_key(key)
        if (
            normalized_key in _NAME_KEYS
            or "legal name" in normalized_key
            or "nome comercial" in normalized_key
        ):
            return candidate
    return None


def merge_product_details(
    search_product: ProductItem, details: dict[str, Any]
) -> ProductItem:
    """Merge a search-page product with its detail-page fields.

    Search identity (``product_id``) always wins; detail fields override search
    fields only when present.
    """
    data = search_product.model_dump()
    data.update({key: value for key, value in details.items() if value is not None})
    data["product_id"] = search_product.product_id
    data["url"] = details.get("url") or search_product.url
    data["vendor_id"] = details.get("vendor_id") or search_product.vendor_id
    data["metadata"] = {
        **(search_product.metadata or {}),
        "details": details.get("details", {}),
        "description": details.get("description"),
        "features": details.get("features", []),
        "reviews": details.get("reviews", []),
    }
    return ProductItem(**data)


def normalize_vendor(
    vendor_id: str, vendor_url: str, details: dict[str, Any]
) -> dict[str, Any]:
    """Normalize raw vendor fields for ``PostgreSQLSink.load_vendor``."""
    seller_info = details.get("seller_info", {})
    extracted_name = details.get("name")
    name = str(extracted_name).strip() if extracted_name is not None else ""
    if not name:
        name = seller_info_name(seller_info) or ""
    if not name:
        logger.warning(
            "Vendor %s has no meaningful extracted seller name; using vendor ID",
            vendor_id,
        )
        name = vendor_id

    cnpj = None
    if isinstance(seller_info, dict):
        for key, value in seller_info.items():
            if isinstance(key, str) and _normalized_key(key) == "cnpj":
                if value is not None:
                    cnpj = str(value).strip() or None
                break

    storefront_url = details.get("storefront_url")
    normalized = {
        "vendor_id": vendor_id,
        "name": name,
        "url": details.get("vendor_url") or vendor_url,
        "cnpj": cnpj,
        "storefront_url": storefront_url,
        "metadata": {
            "storefront_url": storefront_url,
            "seller_info": seller_info,
        },
    }
    logger.info(
        "normalized vendor vendor_id=%s name_present=%s cnpj_present=%s "
        "storefront_present=%s",
        vendor_id,
        bool(normalized["name"]),
        bool(normalized["cnpj"]),
        bool(storefront_url),
    )
    return normalized
