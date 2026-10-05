"""пользователи: users.last_seen — последний авторизованный запрос (кто онлайн)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f60a11
Create Date: 2026-09-15 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f60a11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_seen")
