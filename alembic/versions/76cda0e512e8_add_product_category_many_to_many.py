"""
add product category many to many

Revision ID: 76cda0e512e8
Revises: 141378bd1297
Create Date: 2026-09-18 15:45:07.132479
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "76cda0e512e8"
down_revision: Union[str, Sequence[str], None] = "141378bd1297"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================
    # 1. Create the many-to-many association table
    # =========================================================

    op.create_table(
        "product_categories",

        sa.Column(
            "product_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "category_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="CASCADE",
        ),

        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint(
            "product_id",
            "category_id",
        ),
    )

    # =========================================================
    # 2. Copy existing product-category relationships
    # =========================================================

    op.execute(
        """
        INSERT INTO product_categories (product_id, category_id)
        SELECT id, category_id
        FROM products
        WHERE category_id IS NOT NULL
        """
    )

    # =========================================================
    # 3. Remove old category relationship
    # =========================================================

    op.drop_index(
        op.f("ix_products_category_id"),
        table_name="products",
    )

    op.drop_constraint(
        op.f("products_category_id_fkey"),
        "products",
        type_="foreignkey",
    )

    op.drop_column(
        "products",
        "category_id",
    )


def downgrade() -> None:
    # =========================================================
    # 1. Add category_id back
    # =========================================================

    op.add_column(
        "products",
        sa.Column(
            "category_id",
            sa.INTEGER(),
            nullable=True,
        ),
    )

    # =========================================================
    # 2. Restore one category for each product
    #
    # Since the old structure supported only ONE category,
    # we take the first category associated with each product.
    # =========================================================

    op.execute(
        """
        UPDATE products p
        SET category_id = pc.category_id
        FROM (
            SELECT DISTINCT ON (product_id)
                   product_id,
                   category_id
            FROM product_categories
            ORDER BY product_id, category_id
        ) pc
        WHERE p.id = pc.product_id
        """
    )

    # =========================================================
    # 3. Make category_id NOT NULL again
    # =========================================================

    op.alter_column(
        "products",
        "category_id",
        nullable=False,
    )

    # =========================================================
    # 4. Recreate foreign key
    # =========================================================

    op.create_foreign_key(
        op.f("products_category_id_fkey"),
        "products",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # =========================================================
    # 5. Recreate index
    # =========================================================

    op.create_index(
        op.f("ix_products_category_id"),
        "products",
        ["category_id"],
        unique=False,
    )

    # =========================================================
    # 6. Remove many-to-many table
    # =========================================================

    op.drop_table("product_categories")