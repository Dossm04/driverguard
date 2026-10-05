"""фото водителя: drivers.photo_key (ключ в бакете photos)

Revision ID: c3d4e5f60a11
Revises: 8c2f1a9d4e10
Create Date: 2026-09-15 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f60a11"
down_revision: str | None = "8c2f1a9d4e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drivers", sa.Column("photo_key", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("drivers", "photo_key")
