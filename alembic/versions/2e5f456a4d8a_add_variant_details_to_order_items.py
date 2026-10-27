
"""add variant details to order items

Revision ID: 2e5f456a4d8a
Revises: 96b94cebddc9
Create Date: 2026-10-27 14:34:09.935727
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2e5f456a4d8a"
down_revision: Union[str, Sequence[str], None] = "96b94cebddc9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cart item variants
    op.add_column(
        "cart_items",
        sa.Column("variant_id", sa.Integer(), nullable=True),
    )

    op.drop_constraint(
        "uq_cart_product",
        "cart_items",
        type_="unique",
    )

    op.create_index(
        "ix_cart_items_variant_id",
        "cart_items",
        ["variant_id"],
        unique=False,
    )

    op.create_unique_constraint(
        "uq_cart_product_variant",
        "cart_items",
        ["cart_id", "product_id", "variant_id"],
    )

    op.create_foreign_key(
        "fk_cart_items_variant_id_product_variants",
        "cart_items",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Order item variant snapshots
    op.add_column(
        "order_items",
        sa.Column("variant_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_sku", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_size", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_color", sa.String(length=100), nullable=True),
    )

    op.create_index(
        "ix_order_items_variant_id",
        "order_items",
        ["variant_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_order_items_variant_id_product_variants",
        "order_items",
        "product_variants",
        ["variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # Remove order item variant fields
    op.drop_constraint(
        "fk_order_items_variant_id_product_variants",
        "order_items",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_order_items_variant_id",
        table_name="order_items",
    )

    op.drop_column("order_items", "variant_color")
    op.drop_column("order_items", "variant_size")
    op.drop_column("order_items", "variant_sku")
    op.drop_column("order_items", "variant_id")

    # Restore the original cart constraint
    op.drop_constraint(
        "fk_cart_items_variant_id_product_variants",
        "cart_items",
        type_="foreignkey",
    )

    op.drop_constraint(
        "uq_cart_product_variant",
        "cart_items",
        type_="unique",
    )

    op.drop_index(
        "ix_cart_items_variant_id",
        table_name="cart_items",
    )

    op.create_unique_constraint(
        "uq_cart_product",
        "cart_items",
        ["cart_id", "product_id"],
    )

    op.drop_column("cart_items", "variant_id")
