"""checklists v2: анкета, итоговый вердикт, отметка координатора

Revision ID: 8c2f1a9d4e10
Revises: 567e890e9271
Create Date: 2026-09-02 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "8c2f1a9d4e10"
down_revision: str | None = "567e890e9271"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "checklists", sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column("checklists", sa.Column("verdict", sa.String(length=20), nullable=True))
    op.add_column("checklists", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("checklists", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_checklists_verdict", "checklists", ["verdict"])


def downgrade() -> None:
    op.drop_index("ix_checklists_verdict", table_name="checklists")
    op.drop_column("checklists", "reviewed_at")
    op.drop_column("checklists", "note")
    op.drop_column("checklists", "verdict")
    op.drop_column("checklists", "answers")
