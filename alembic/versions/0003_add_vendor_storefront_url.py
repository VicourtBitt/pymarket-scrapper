"""Add first-class storefront URLs to vendors.

Revision ID: 0003_add_vendor_storefront_url
Revises: 0002_add_vendor_cnpj
"""

from typing import Optional

from alembic import op
import sqlalchemy as sa

revision: str = "0003_add_vendor_storefront_url"
down_revision: Optional[str] = "0002_add_vendor_cnpj"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    """Add an optional storefront URL to vendors."""
    op.add_column(
        "vendors",
        sa.Column("storefront_url", sa.String(2048), nullable=True),
    )


def downgrade() -> None:
    """Remove the optional vendor storefront URL."""
    op.drop_column("vendors", "storefront_url")
