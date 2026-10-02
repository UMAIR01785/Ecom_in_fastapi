"""create payments

Revision ID: c9f5d3a39992
Revises: 03b5ba3e8e41
Create Date: 2026-09-28 15:31:27.930376
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9f5d3a39992"
down_revision: Union[str, Sequence[str], None] = "03b5ba3e8e41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payments",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
        ),

        sa.Column(
            "order_id",
            sa.Integer(),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),

        sa.Column(
            "amount",
            sa.Numeric(10, 2),
            nullable=False,
        ),

        sa.Column(
            "method",
            sa.Enum(
                "COD",
                "CARD",
                name="paymentmethod",
            ),
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

        sa.Column(
            "session_id",
            sa.String(255),
            nullable=True,
        ),

        sa.Column(
            "transaction_id",
            sa.String(255),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("payments")

    sa.Enum(
        "COD",
        "CARD",
        name="paymentmethod",
    ).drop(op.get_bind(), checkfirst=True)

    sa.Enum(
        "PENDING",
        "PAID",
        "FAILED",
        "CANCELLED",
        name="paymentstatus",
    ).drop(op.get_bind(), checkfirst=True)