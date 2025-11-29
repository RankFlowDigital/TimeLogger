"""Add invitation tracking fields to users

Revision ID: 20241129_110000
Revises: 20241128_120000
Create Date: 2025-11-29 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20241129_110000"
down_revision = "20241128_120000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("invited_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("joined_at", sa.DateTime(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "must_reset_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.execute("UPDATE users SET joined_at = created_at WHERE joined_at IS NULL")
    op.alter_column("users", "must_reset_password", server_default=None)


def downgrade():
    op.drop_column("users", "must_reset_password")
    op.drop_column("users", "joined_at")
    op.drop_column("users", "invited_at")
