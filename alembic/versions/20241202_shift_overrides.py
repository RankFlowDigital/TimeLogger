"""Allow manual shift overrides

Revision ID: 20241202_shift_overrides
Revises: 20241201_shift_templates
Create Date: 2025-12-01 18:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20241202_shift_overrides"
down_revision: Union[str, None] = "20241201_shift_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "allow_unassigned_sessions",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "allow_unassigned_sessions")
