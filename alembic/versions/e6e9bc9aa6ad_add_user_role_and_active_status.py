"""add user role and active status

Revision ID: e6e9bc9aa6ad
Revises: 22fa7d700ca4
Create Date: 2026-09-16 16:26:30.459826

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6e9bc9aa6ad"
down_revision: Union[str, Sequence[str], None] = "22fa7d700ca4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create PostgreSQL enum type
    user_role = sa.Enum(
        "CUSTOMER",
        "ADMIN",
        name="userrole",
    )

    user_role.create(op.get_bind(), checkfirst=True)

    # Add role column
    op.add_column(
        "users",
        sa.Column(
            "role",
            user_role,
            nullable=False,
            server_default="CUSTOMER",
        ),
    )

    # Add is_active column
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # Remove temporary defaults
    op.alter_column(
        "users",
        "role",
        server_default=None,
    )

    op.alter_column(
        "users",
        "is_active",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")

    # Remove PostgreSQL enum type
    user_role = sa.Enum(
        "CUSTOMER",
        "ADMIN",
        name="userrole",
    )

    user_role.drop(op.get_bind(), checkfirst=True)