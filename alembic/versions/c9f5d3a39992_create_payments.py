"""create payments

Revision ID: c9f5d3a39992
Revises: 03b5ba3e8e41
"""
from alembic import op
import sqlalchemy as sa


revision = "c9f5d3a39992"
down_revision = "03b5ba3e8e41"
branch_labels = None
depends_on = None


def upgrade():
    payment_method = sa.Enum(
        "card",
        "cod",
        name="paymentmethod",
    )

    payment_status = sa.Enum(
        "pending",
        "paid",
        "failed",
        "refunded",
        name="paymentstatus",
    )

    payment_method.create(op.get_bind(), checkfirst=True)
    payment_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payments",

        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
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
            payment_method,
            nullable=False,
        ),

        sa.Column(
            "status",
            payment_status,
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
            unique=True,
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

    op.create_index(
        "ix_payments_order_id",
        "payments",
        ["order_id"],
    )

    op.create_index(
        "ix_payments_session_id",
        "payments",
        ["session_id"],
    )


def downgrade():

    op.drop_index(
        "ix_payments_session_id",
        table_name="payments",
    )

    op.drop_index(
        "ix_payments_order_id",
        table_name="payments",
    )

    op.drop_table("payments")

    payment_status = sa.Enum(
        "pending",
        "paid",
        "failed",
        "refunded",
        name="paymentstatus",
    )

    payment_method = sa.Enum(
        "card",
        "cod",
        name="paymentmethod",
    )

    payment_status.drop(op.get_bind(), checkfirst=True)
    payment_method.drop(op.get_bind(), checkfirst=True)