"""Preserve native DMS observations with each offline event.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    # Existing events remain unchanged; absent measurements are not zero readings.
    op.add_column("events", sa.Column("measurements", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("events", "measurements")
