"""init

Revision ID: 20241128_120000
Revises:
Create Date: 2025-11-28 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20241128_120000"
down_revision: Union[str, None] = "0005_conversation_otp"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


user_role_enum = sa.Enum("OWNER", "ADMIN", "MEMBER", name="user_role")
session_type_enum = sa.Enum("WORK", "LUNCH", "SHORT_BREAK", name="session_type")
rollcall_result_enum = sa.Enum("PENDING", "PASSED", "LATE", "MISSED", name="rollcall_result")
leave_type_enum = sa.Enum("LEAVE", "DAY_OFF", name="leave_type")
deduction_type_enum = sa.Enum("OVERBREAK", "ROLLCALL", name="deduction_type")


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), onupdate=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("role", user_role_enum, nullable=False, server_default="MEMBER"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("timezone", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), onupdate=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_foreign_key(
        "organizations_owner_user_id_fkey",
        "organizations",
        "users",
        ["owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "shifts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "leaves",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("type", leave_type_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "work_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("task_description", sa.Text(), nullable=True),
        sa.Column("session_type", session_type_enum, nullable=False, server_default="WORK"),
        sa.Column("source", sa.String(), nullable=True),
    )

    op.create_table(
        "roll_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.Column("result", rollcall_result_enum, nullable=False, server_default="PENDING"),
        sa.Column("response_delay_seconds", sa.Integer(), nullable=True),
    )

    op.create_table(
        "deductions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("type", deduction_type_enum, nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("related_session_id", sa.Integer(), sa.ForeignKey("work_sessions.id"), nullable=True),
        sa.Column("related_roll_call_id", sa.Integer(), sa.ForeignKey("roll_calls.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("deductions")
    op.drop_table("roll_calls")
    op.drop_table("work_sessions")
    op.drop_table("leaves")
    op.drop_table("shifts")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("organizations")

    deduction_type_enum.drop(op.get_bind(), checkfirst=False)
    leave_type_enum.drop(op.get_bind(), checkfirst=False)
    rollcall_result_enum.drop(op.get_bind(), checkfirst=False)
    session_type_enum.drop(op.get_bind(), checkfirst=False)
    user_role_enum.drop(op.get_bind(), checkfirst=False)
