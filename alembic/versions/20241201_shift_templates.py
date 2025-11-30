"""Shift templates and assignments

Revision ID: 20241201_shift_templates
Revises: 20241128_120000
Create Date: 2025-12-01 12:00:00.000000
"""

from datetime import date
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20241201_shift_templates"
down_revision: Union[str, None] = "20241128_120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("shifts", "shift_templates")

    op.add_column("shift_templates", sa.Column("name", sa.String(length=120), nullable=True))
    op.add_column("shift_templates", sa.Column("timezone", sa.String(length=64), nullable=True))

    op.create_table(
        "shift_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shift_id", sa.Integer(), sa.ForeignKey("shift_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("shift_id", "user_id", "effective_from", name="uq_shift_assignment_start"),
    )
    op.create_index("ix_shift_assignments_user_id", "shift_assignments", ["user_id"])
    op.create_index("ix_shift_assignments_shift_id", "shift_assignments", ["shift_id"])

    conn = op.get_bind()
    today = date.today()
    rows = conn.execute(sa.text("SELECT id, user_id FROM shift_templates WHERE user_id IS NOT NULL")).fetchall()
    if rows:
        conn.execute(
            sa.text(
                "INSERT INTO shift_assignments (shift_id, user_id, effective_from) VALUES (:shift_id, :user_id, :effective_from)"
            ),
            [
                {"shift_id": row.id, "user_id": row.user_id, "effective_from": today}
                for row in rows
                if row.user_id is not None
            ],
        )

    op.drop_constraint("shifts_user_id_fkey", "shift_templates", type_="foreignkey")
    op.drop_column("shift_templates", "user_id")


def downgrade() -> None:
    op.add_column(
        "shift_templates",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
    )

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT shift_id, user_id FROM shift_assignments"))
    for row in rows:
        conn.execute(
            sa.text("UPDATE shift_templates SET user_id = :user_id WHERE id = :shift_id"),
            {"user_id": row.user_id, "shift_id": row.shift_id},
        )

    op.drop_index("ix_shift_assignments_shift_id", table_name="shift_assignments")
    op.drop_index("ix_shift_assignments_user_id", table_name="shift_assignments")
    op.drop_table("shift_assignments")

    op.drop_column("shift_templates", "timezone")
    op.drop_column("shift_templates", "name")
    op.rename_table("shift_templates", "shifts")
*** End of File***