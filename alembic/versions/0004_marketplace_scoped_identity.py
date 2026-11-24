"""Scope product and vendor identity to the marketplace.

Product and seller IDs are only unique within one marketplace configuration
(ASINs, for example, are shared across Amazon sites). Products become
``(marketplace, product_id)``, vendors gain a ``marketplace`` column and become
``(marketplace, vendor_id)``, and observations carry ``marketplace`` so every
foreign key is composite.

Existing vendors take the marketplace of the products/observations that
reference them; a vendor referenced from several marketplaces is copied into
each. Vendors referenced by nothing use the only marketplace present in
``products``, or the value given with::

    alembic -x default_marketplace=<name> upgrade head

Vendor foreign keys use NO ACTION (a referenced vendor cannot be deleted)
instead of SET NULL, because nulling a composite key would also null the
non-nullable ``marketplace`` column.

Revision ID: 0004_marketplace_scoped_identity
Revises: 0003_add_vendor_storefront_url
"""

from typing import Optional

from alembic import context, op
import sqlalchemy as sa

revision: str = "0004_marketplace_scoped_identity"
down_revision: Optional[str] = "0003_add_vendor_storefront_url"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

_VENDOR_COLUMNS = (
    "vendor_id, name, url, extracted_phones, extracted_emails, external_id, "
    "metadata_blob, cnpj, storefront_url"
)
_VENDOR_SOURCE_COLUMNS = ", ".join(f"v.{c.strip()}" for c in _VENDOR_COLUMNS.split(","))


def _default_marketplace(bind: sa.engine.Connection) -> Optional[str]:
    explicit = context.get_x_argument(as_dictionary=True).get("default_marketplace")
    if explicit:
        return explicit
    marketplaces = bind.execute(sa.text("SELECT DISTINCT marketplace FROM products")).scalars().all()
    return marketplaces[0] if len(marketplaces) == 1 else None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Drop single-column foreign keys and the keys they depend on.
    op.drop_constraint("products_vendor_id_fkey", "products", type_="foreignkey")
    op.drop_constraint(
        "product_observations_product_id_fkey", "product_observations", type_="foreignkey"
    )
    op.drop_constraint(
        "product_observations_vendor_id_fkey", "product_observations", type_="foreignkey"
    )

    # 2. Observations carry their product's marketplace (product_id is still
    #    globally unique at this point, so the join is unambiguous).
    op.add_column("product_observations", sa.Column("marketplace", sa.String(100), nullable=True))
    op.execute(
        """
        UPDATE product_observations o
        SET marketplace = p.marketplace
        FROM products p
        WHERE p.product_id = o.product_id
        """
    )
    op.alter_column("product_observations", "marketplace", nullable=False)

    # 3. Vendors: assign a marketplace, copying vendors used by several.
    op.add_column("vendors", sa.Column("marketplace", sa.String(100), nullable=True))
    op.drop_constraint("vendors_pkey", "vendors", type_="primary")
    referenced_pairs = """
        SELECT marketplace, vendor_id FROM products WHERE vendor_id IS NOT NULL
        UNION
        SELECT marketplace, vendor_id FROM product_observations WHERE vendor_id IS NOT NULL
    """
    op.execute(
        f"""
        UPDATE vendors v
        SET marketplace = pairs.marketplace
        FROM (
            SELECT vendor_id, min(marketplace) AS marketplace
            FROM ({referenced_pairs}) referenced
            GROUP BY vendor_id
        ) pairs
        WHERE v.vendor_id = pairs.vendor_id
        """
    )
    op.execute(
        f"""
        INSERT INTO vendors (marketplace, {_VENDOR_COLUMNS})
        SELECT pairs.marketplace, {_VENDOR_SOURCE_COLUMNS}
        FROM ({referenced_pairs}) pairs
        JOIN vendors v
          ON v.vendor_id = pairs.vendor_id AND v.marketplace <> pairs.marketplace
        """
    )
    unassigned = bind.execute(
        sa.text("SELECT count(*) FROM vendors WHERE marketplace IS NULL")
    ).scalar_one()
    if unassigned:
        default = _default_marketplace(bind)
        if not default:
            raise RuntimeError(
                f"{unassigned} vendor(s) are not referenced by any product and the "
                "database holds several (or no) marketplaces. Re-run with "
                "'alembic -x default_marketplace=<name> upgrade head'."
            )
        bind.execute(
            sa.text("UPDATE vendors SET marketplace = :marketplace WHERE marketplace IS NULL"),
            {"marketplace": default},
        )
    op.alter_column("vendors", "marketplace", nullable=False)
    op.create_primary_key("vendors_pkey", "vendors", ["marketplace", "vendor_id"])

    # 4. Products: composite primary key and marketplace-scoped vendor index.
    op.drop_constraint("products_pkey", "products", type_="primary")
    op.create_primary_key("products_pkey", "products", ["marketplace", "product_id"])
    op.drop_index("ix_products_product_id", table_name="products")
    op.drop_index("ix_products_vendor_id", table_name="products")
    op.create_index("ix_products_marketplace_vendor_id", "products", ["marketplace", "vendor_id"])
    op.drop_index("ix_observations_product_observed_at", table_name="product_observations")
    op.create_index(
        "ix_observations_product_observed_at",
        "product_observations",
        ["marketplace", "product_id", "observed_at"],
    )

    # 5. Composite foreign keys.
    op.create_foreign_key(
        "fk_products_vendor", "products", "vendors",
        ["marketplace", "vendor_id"], ["marketplace", "vendor_id"],
    )
    op.create_foreign_key(
        "fk_observations_product", "product_observations", "products",
        ["marketplace", "product_id"], ["marketplace", "product_id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_observations_vendor", "product_observations", "vendors",
        ["marketplace", "vendor_id"], ["marketplace", "vendor_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table, column in (("products", "product_id"), ("vendors", "vendor_id")):
        duplicated = bind.execute(
            sa.text(
                f"SELECT count(*) FROM (SELECT {column} FROM {table} "
                f"GROUP BY {column} HAVING count(*) > 1) d"
            )
        ).scalar_one()
        if duplicated:
            raise RuntimeError(
                f"Cannot downgrade: {duplicated} {column} value(s) exist in several "
                f"marketplaces in '{table}'; global IDs would collide."
            )

    op.drop_constraint("fk_observations_vendor", "product_observations", type_="foreignkey")
    op.drop_constraint("fk_observations_product", "product_observations", type_="foreignkey")
    op.drop_constraint("fk_products_vendor", "products", type_="foreignkey")

    op.drop_index("ix_observations_product_observed_at", table_name="product_observations")
    op.create_index(
        "ix_observations_product_observed_at", "product_observations", ["product_id", "observed_at"]
    )
    op.drop_index("ix_products_marketplace_vendor_id", table_name="products")
    op.create_index("ix_products_vendor_id", "products", ["vendor_id"])
    op.create_index("ix_products_product_id", "products", ["product_id"])
    op.drop_constraint("products_pkey", "products", type_="primary")
    op.create_primary_key("products_pkey", "products", ["product_id"])

    op.drop_constraint("vendors_pkey", "vendors", type_="primary")
    op.drop_column("vendors", "marketplace")
    op.create_primary_key("vendors_pkey", "vendors", ["vendor_id"])
    op.drop_column("product_observations", "marketplace")

    op.create_foreign_key(
        "products_vendor_id_fkey", "products", "vendors",
        ["vendor_id"], ["vendor_id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "product_observations_product_id_fkey", "product_observations", "products",
        ["product_id"], ["product_id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "product_observations_vendor_id_fkey", "product_observations", "vendors",
        ["vendor_id"], ["vendor_id"], ondelete="SET NULL",
    )
