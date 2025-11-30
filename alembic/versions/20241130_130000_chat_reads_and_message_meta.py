"""chat reads and message metadata

Revision ID: 20241130_130000
Revises: 20241129_150000
Create Date: 2025-11-30 13:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20241130_130000"
down_revision: Union[str, None] = "20241129_150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


message_type_enum = sa.Enum(
    "CHAT",
    "SYSTEM",
    "BROADCAST",
    "ROLL_CALL",
    name="message_type",
)


def upgrade() -> None:
    bind = op.get_bind()
    message_type_enum.create(bind, checkfirst=True)
    op.add_column(
        "messages",
        sa.Column("message_type", message_type_enum, nullable=False, server_default="CHAT"),
    )
    op.add_column(
        "messages",
        sa.Column("metadata", sa.JSON(), nullable=True),
    )

    op.create_table(
        "chat_room_reads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_read_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("room_id", "user_id", name="uq_chat_room_read_member"),
    )
    op.create_index("ix_chat_room_reads_room_user", "chat_room_reads", ["room_id", "user_id"], unique=True)

    op.execute("UPDATE messages SET message_type = 'CHAT' WHERE message_type IS NULL")
    op.alter_column("messages", "message_type", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_chat_room_reads_room_user", table_name="chat_room_reads")
    op.drop_table("chat_room_reads")
    op.drop_column("messages", "metadata")
    op.drop_column("messages", "message_type")
    message_type_enum.drop(op.get_bind(), checkfirst=True)
