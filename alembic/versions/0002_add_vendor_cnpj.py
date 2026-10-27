"""Add CNPJ persistence to vendors.

Revision ID: 0002_add_vendor_cnpj
Revises: 0001_extraction_persistence
"""

from typing import Optional

from alembic import op
import sqlalchemy as sa

revision: str = "0002_add_vendor_cnpj"
down_revision: Optional[str] = "0001_extraction_persistence"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    """Add an optional formatted or unformatted CNPJ to vendors."""
    op.add_column("vendors", sa.Column("cnpj", sa.String(32), nullable=True))


def downgrade() -> None:
    """Remove the optional vendor CNPJ column."""
    op.drop_column("vendors", "cnpj")