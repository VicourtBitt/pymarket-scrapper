"""Initial extraction persistence schema.

Revision ID: 0001_extraction_persistence
"""

from typing import Optional

from alembic import op
import sqlalchemy as sa

revision: str = "0001_extraction_persistence"
down_revision: Optional[str] = None
branch_labels: Optional[str] = None
depends_on: Optional[str] = None


def upgrade() -> None:
    """Create vendors, canonical products, and extraction observation tables."""
    op.create_table(
        "vendors",
        sa.Column("vendor_id", sa.String(255), primary_key=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("url", sa.String(2048)),
        sa.Column("extracted_phones", sa.JSON(), nullable=False),
        sa.Column("extracted_emails", sa.JSON(), nullable=False),
        sa.Column("external_id", sa.String(255)),
        sa.Column("metadata_blob", sa.JSON(), nullable=False),
    )
    op.create_index("ix_vendors_external_id", "vendors", ["external_id"])
    op.create_table(
        "extraction_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("marketplace", sa.String(100), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("config_hash", sa.String(128)),
        sa.Column("requested_by", sa.String(255)),
        sa.Column("source", sa.String(255)),
        sa.Column("rows_extracted", sa.Integer(), nullable=False),
        sa.Column("rows_loaded", sa.Integer(), nullable=False),
        sa.Column("rows_failed", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.String(4000)),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_index("ix_extraction_runs_marketplace", "extraction_runs", ["marketplace"])
    op.create_index("ix_extraction_runs_status", "extraction_runs", ["status"])
    op.create_table(
        "products",
        sa.Column("product_id", sa.String(255), primary_key=True),
        sa.Column("marketplace", sa.String(100), nullable=False),
        sa.Column("external_product_id", sa.String(255)),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("url", sa.String(2048)),
        sa.Column("price", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(12)),
        sa.Column("vendor_id", sa.String(255), sa.ForeignKey("vendors.vendor_id", ondelete="SET NULL")),
        sa.Column("metadata_blob", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("marketplace", "external_product_id", name="uq_products_marketplace_external_id"),
    )
    op.create_index("ix_products_product_id", "products", ["product_id"])
    op.create_index("ix_products_marketplace_title", "products", ["marketplace", "title"])
    op.create_index("ix_products_vendor_id", "products", ["vendor_id"])
    op.create_table(
        "extraction_searches",
        sa.Column("search_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("extraction_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("search_term", sa.String(500), nullable=False),
        sa.Column("sort_strategy", sa.String(100)),
        sa.Column("requested_limit", sa.Integer()),
        sa.Column("rows_extracted", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_extraction_searches_run_id", "extraction_searches", ["run_id"])
    op.create_index("ix_extraction_searches_status", "extraction_searches", ["status"])
    op.create_table(
        "product_observations",
        sa.Column("observation_id", sa.String(36), primary_key=True),
        sa.Column("search_id", sa.String(36), sa.ForeignKey("extraction_searches.search_id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.String(255), sa.ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(1000)),
        sa.Column("url", sa.String(2048)),
        sa.Column("price", sa.Numeric(18, 4)),
        sa.Column("currency", sa.String(12)),
        sa.Column("vendor_id", sa.String(255), sa.ForeignKey("vendors.vendor_id", ondelete="SET NULL")),
        sa.Column("position", sa.Integer()),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("row_hash", sa.String(128), nullable=False),
        sa.UniqueConstraint("search_id", "product_id", "row_hash", name="uq_observation_search_product_hash"),
    )
    op.create_index("ix_observations_product_observed_at", "product_observations", ["product_id", "observed_at"])
    op.create_index("ix_observations_search_position", "product_observations", ["search_id", "position"])


def downgrade() -> None:
    """Drop the initial persistence schema in dependency order."""
    op.drop_table("product_observations")
    op.drop_table("extraction_searches")
    op.drop_table("products")
    op.drop_table("extraction_runs")
    op.drop_table("vendors")
