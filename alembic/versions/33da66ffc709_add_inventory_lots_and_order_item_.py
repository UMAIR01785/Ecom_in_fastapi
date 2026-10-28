
"""add inventory lots and order item allocations

Revision ID: 33da66ffc709
Revises: 2e5f456a4d8a
Create Date: 2026-10-27 17:11:04.357265
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers used by Alembic.
revision: str = "33da66ffc709"
down_revision: Union[str, Sequence[str], None] = "2e5f456a4d8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create inventory lot tables and initialize existing stock."""

    # ---------------------------------------------------------
    # 1. Inventory lots
    # ---------------------------------------------------------
    op.create_table(
        "inventory_lots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lot_number", sa.String(length=100), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("quantity_remaining", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),

        sa.CheckConstraint(
            """
            (
                product_id IS NOT NULL
                AND variant_id IS NULL
            )
            OR
            (
                product_id IS NULL
                AND variant_id IS NOT NULL
            )
            """,
            name="ck_inventory_lot_exactly_one_owner",
        ),
        sa.CheckConstraint(
            "quantity_received > 0",
            name="ck_inventory_lot_received_positive",
        ),
        sa.CheckConstraint(
            "quantity_remaining <= quantity_received",
            name="ck_inventory_lot_remaining_lte_received",
        ),
        sa.CheckConstraint(
            "quantity_remaining >= 0",
            name="ck_inventory_lot_remaining_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["product_variants.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Inventory lot indexes.
    op.create_index(
        op.f("ix_inventory_lots_expires_at"),
        "inventory_lots",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_lots_id"),
        "inventory_lots",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_lots_lot_number"),
        "inventory_lots",
        ["lot_number"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_lots_product_expiry",
        "inventory_lots",
        ["product_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_lots_product_id"),
        "inventory_lots",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_lots_variant_expiry",
        "inventory_lots",
        ["variant_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_inventory_lots_variant_id"),
        "inventory_lots",
        ["variant_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # 2. Order item lot allocations
    # ---------------------------------------------------------
    op.create_table(
        "order_item_lots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=False),
        sa.Column("inventory_lot_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),

        sa.CheckConstraint(
            "quantity > 0",
            name="ck_order_item_lot_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_lot_id"],
            ["inventory_lots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_item_id",
            "inventory_lot_id",
            name="uq_order_item_inventory_lot",
        ),
    )

    # Order item lot indexes.
    op.create_index(
        op.f("ix_order_item_lots_id"),
        "order_item_lots",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_item_lots_inventory_lot_id"),
        "order_item_lots",
        ["inventory_lot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_item_lots_order_item_id"),
        "order_item_lots",
        ["order_item_id"],
        unique=False,
    )

    # ---------------------------------------------------------
    # 3. Backfill opening lots for existing inventory
    # ---------------------------------------------------------
    # Only standalone products receive product-level lots.
    # Products with variants use variant-level inventory instead.
    op.execute(
        """
        INSERT INTO inventory_lots (
            lot_number,
            product_id,
            variant_id,
            quantity_received,
            quantity_remaining,
            expires_at,
            received_at,
            created_at,
            updated_at
        )
        SELECT
            'OPENING-PRODUCT-' || p.id,
            p.id,
            NULL,
            p.stock,
            p.stock,
            NULL,
            NOW(),
            NOW(),
            NOW()
        FROM products AS p
        WHERE p.stock > 0
          AND NOT EXISTS (
              SELECT 1
              FROM product_variants AS pv
              WHERE pv.product_id = p.id
          )
        """
    )

    # Existing variant stock becomes variant-level opening lots.
    op.execute(
        """
        INSERT INTO inventory_lots (
            lot_number,
            product_id,
            variant_id,
            quantity_received,
            quantity_remaining,
            expires_at,
            received_at,
            created_at,
            updated_at
        )
        SELECT
            'OPENING-VARIANT-' || pv.id,
            NULL,
            pv.id,
            pv.stock,
            pv.stock,
            NULL,
            NOW(),
            NOW(),
            NOW()
        FROM product_variants AS pv
        WHERE pv.stock > 0
        """
    )


def downgrade() -> None:
    """Remove inventory lot tables."""

    # Remove order-item allocations first because they reference inventory_lots.
    op.drop_index(
        op.f("ix_order_item_lots_order_item_id"),
        table_name="order_item_lots",
    )
    op.drop_index(
        op.f("ix_order_item_lots_inventory_lot_id"),
        table_name="order_item_lots",
    )
    op.drop_index(
        op.f("ix_order_item_lots_id"),
        table_name="order_item_lots",
    )
    op.drop_table("order_item_lots")

    # Remove inventory lot indexes.
    op.drop_index(
        op.f("ix_inventory_lots_variant_id"),
        table_name="inventory_lots",
    )
    op.drop_index(
        "ix_inventory_lots_variant_expiry",
        table_name="inventory_lots",
    )
    op.drop_index(
        op.f("ix_inventory_lots_product_id"),
        table_name="inventory_lots",
    )
    op.drop_index(
        "ix_inventory_lots_product_expiry",
        table_name="inventory_lots",
    )
    op.drop_index(
        op.f("ix_inventory_lots_lot_number"),
        table_name="inventory_lots",
    )
    op.drop_index(
        op.f("ix_inventory_lots_id"),
        table_name="inventory_lots",
    )
    op.drop_index(
        op.f("ix_inventory_lots_expires_at"),
        table_name="inventory_lots",
    )
    op.drop_table("inventory_lots")
