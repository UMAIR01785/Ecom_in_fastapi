"""recreate missing payments table

Revision ID: 1c54cd13301c
Revises: 4a4fd64044f4
Create Date: 2026-10-02 13:14:52.771380

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c54cd13301c'
down_revision: Union[str, Sequence[str], None] = '4a4fd64044f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "method",
            sa.Enum("COD", "CARD", name="paymentmethod"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "PAID",
                "FAILED",
                "CANCELLED",
                name="paymentstatus",
            ),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("transaction_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id"),
    )

    op.create_index(
        "ix_payments_id",
        "payments",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_payments_order_id",
        "payments",
        ["order_id"],
        unique=False,
    )

    op.create_index(
        "ix_payments_session_id",
        "payments",
        ["session_id"],
        unique=False,
    )

def downgrade() -> None:
    op.drop_index("ix_payments_session_id", table_name="payments")
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_index("ix_payments_id", table_name="payments")
    op.drop_table("payments")