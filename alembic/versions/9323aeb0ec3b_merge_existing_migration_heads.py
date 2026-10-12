"""merge existing migration heads

Revision ID: 9323aeb0ec3b
Revises: cdf96b693928
Create Date: 2026-10-12 15:02:48.906971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9323aeb0ec3b'
down_revision: Union[str, Sequence[str], None] = 'cdf96b693928'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
