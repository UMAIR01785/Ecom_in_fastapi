"""add inventory reservation fields

Revision ID: 6f71134ecae3
Revises: 45c586779095
Create Date: 2026-10-14 14:01:55.548272

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f71134ecae3'
down_revision: Union[str, Sequence[str], None] = '45c586779095'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "reservation_expires_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.add_column(
        "orders",
        sa.Column(
            "inventory_released_at",
            sa.DateTime(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_orders_reservation_expires_at",
        "orders",
        ["reservation_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orders_reservation_expires_at",
        table_name="orders",
    )

    op.drop_column("orders", "inventory_released_at")
    op.drop_column("orders", "reservation_expires_at")