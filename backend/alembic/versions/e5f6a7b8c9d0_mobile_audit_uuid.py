"""Idempotent mobile audit submissions.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

import sqlalchemy as sa

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("checklists", sa.Column("client_uuid", sa.String(36), nullable=True))
    op.create_index(
        "uq_checklists_driver_client_uuid", "checklists", ["driver_id", "client_uuid"], unique=True
    )


def downgrade():
    op.drop_index("uq_checklists_driver_client_uuid", table_name="checklists")
    op.drop_column("checklists", "client_uuid")
