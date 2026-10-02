"""fix payment enums

Revision ID: 4a4fd64044f4
Revises: c9f5d3a39992
Create Date: 2026-10-02 13:08:28.284409

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a4fd64044f4'
down_revision: Union[str, Sequence[str], None] = 'c9f5d3a39992'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
