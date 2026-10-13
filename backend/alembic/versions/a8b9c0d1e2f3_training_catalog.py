"""Add missing learning catalog entries without assigning or completing lessons.

Revision ID: a8b9c0d1e2f3
Revises: f6a7b8c9d0e1
"""

import sqlalchemy as sa

from alembic import op

revision = "a8b9c0d1e2f3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None
TITLES = ("Управление усталостью", "Техника перерывов в рейсе", "Телефон и дорога")


def upgrade():
    connection = op.get_bind()
    for title in TITLES:
        connection.execute(
            sa.text(
                "INSERT INTO trainings (title, duration_s) SELECT CAST(:title AS VARCHAR), 30 "
                "WHERE NOT EXISTS (SELECT 1 FROM trainings WHERE title=CAST(:title AS VARCHAR))"
            ),
            {"title": title},
        )


def downgrade():
    # Catalog items may already have assignments; preserve user history on rollback.
    pass
