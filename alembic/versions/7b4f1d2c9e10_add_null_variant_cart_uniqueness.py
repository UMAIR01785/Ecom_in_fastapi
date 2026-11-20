"""prevent duplicate cart rows for products without variants

Revision ID: 7b4f1d2c9e10
Revises: 2e5f456a4d8a
Create Date: 2026-11-13 17:10:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "7b4f1d2c9e10"
down_revision: Union[str, Sequence[str], None] = "2e5f456a4d8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Consolidate legacy duplicates before creating the partial unique index.
    op.execute(
        """
        WITH duplicate_groups AS (
            SELECT
                MIN(id) AS keep_id,
                cart_id,
                product_id,
                SUM(quantity) AS total_quantity
            FROM cart_items
            WHERE variant_id IS NULL
            GROUP BY cart_id, product_id
            HAVING COUNT(*) > 1
        ),
        updated AS (
            UPDATE cart_items item
            SET quantity = duplicate_groups.total_quantity
            FROM duplicate_groups
            WHERE item.id = duplicate_groups.keep_id
            RETURNING item.id
        )
        DELETE FROM cart_items item
        USING duplicate_groups
        WHERE item.cart_id = duplicate_groups.cart_id
          AND item.product_id = duplicate_groups.product_id
          AND item.variant_id IS NULL
          AND item.id <> duplicate_groups.keep_id
        """
    )

    op.create_index(
        "uq_cart_product_without_variant",
        "cart_items",
        ["cart_id", "product_id"],
        unique=True,
        postgresql_where="variant_id IS NULL",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_cart_product_without_variant",
        table_name="cart_items",
    )
