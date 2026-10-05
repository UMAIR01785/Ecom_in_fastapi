"""add order address

Revision ID: cdf96b693928
Revises: 86316c832e62
Create Date: 2026-10-05 15:36:55.761154

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# ============================================================
# REVISION
# ============================================================

revision: str = "cdf96b693928"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "86316c832e62"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


# ============================================================
# UPGRADE
# ============================================================

def upgrade() -> None:

    # --------------------------------------------------------
    # 1. Create order_addresses table
    # --------------------------------------------------------

    op.create_table(
        "order_addresses",

        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "order_id",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "full_name",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "phone_number",
            sa.String(length=20),
            nullable=False,
        ),

        sa.Column(
            "address_line1",
            sa.String(length=255),
            nullable=False,
        ),

        sa.Column(
            "address_line2",
            sa.String(length=255),
            nullable=True,
        ),

        sa.Column(
            "city",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "state",
            sa.String(length=100),
            nullable=True,
        ),

        sa.Column(
            "postal_code",
            sa.String(length=20),
            nullable=True,
        ),

        sa.Column(
            "country",
            sa.String(length=100),
            nullable=False,
        ),

        sa.Column(
            "landmark",
            sa.String(length=255),
            nullable=True,
        ),

        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            ondelete="CASCADE",
        ),

        sa.PrimaryKeyConstraint("id"),
    )

    # --------------------------------------------------------
    # 2. Create indexes
    # --------------------------------------------------------

    op.create_index(
        op.f("ix_order_addresses_id"),
        "order_addresses",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_order_addresses_order_id"),
        "order_addresses",
        ["order_id"],
        unique=True,
    )

    # --------------------------------------------------------
    # 3. Migrate existing order addresses
    #
    # OLD:
    # orders.shipping_address
    #
    # NEW:
    # order_addresses.address_line1
    #
    # Name + phone come from users.
    # City comes from the user's current profile.
    # --------------------------------------------------------

    op.execute(
        """
        INSERT INTO order_addresses (
            order_id,
            full_name,
            phone_number,
            address_line1,
            city,
            country
        )
        SELECT
            o.id,
            u.first_name || ' ' || u.last_name,
            u.phone_number,
            o.shipping_address,
            COALESCE(p.city, 'Unknown'),
            'Pakistan'
        FROM orders o
        JOIN users u
            ON u.id = o.user_id
        LEFT JOIN profiles p
            ON p.user_id = o.user_id
        WHERE o.shipping_address IS NOT NULL
        """
    )

    # --------------------------------------------------------
    # 4. Now remove old shipping_address column
    # --------------------------------------------------------

    op.drop_column(
        "orders",
        "shipping_address",
    )


# ============================================================
# DOWNGRADE
# ============================================================

def downgrade() -> None:

    # --------------------------------------------------------
    # 1. Restore old column
    # --------------------------------------------------------

    op.add_column(
        "orders",
        sa.Column(
            "shipping_address",
            sa.VARCHAR(length=500),
            nullable=True,
        ),
    )

    # --------------------------------------------------------
    # 2. Restore old address values
    # --------------------------------------------------------

    op.execute(
        """
        UPDATE orders o
        SET shipping_address = oa.address_line1
        FROM order_addresses oa
        WHERE oa.order_id = o.id
        """
    )

    # --------------------------------------------------------
    # 3. Make old column NOT NULL again
    # --------------------------------------------------------

    op.alter_column(
        "orders",
        "shipping_address",
        existing_type=sa.VARCHAR(length=500),
        nullable=False,
    )

    # --------------------------------------------------------
    # 4. Remove indexes
    # --------------------------------------------------------

    op.drop_index(
        op.f("ix_order_addresses_order_id"),
        table_name="order_addresses",
    )

    op.drop_index(
        op.f("ix_order_addresses_id"),
        table_name="order_addresses",
    )

    # --------------------------------------------------------
    # 5. Remove order_addresses table
    # --------------------------------------------------------

    op.drop_table(
        "order_addresses",
    )