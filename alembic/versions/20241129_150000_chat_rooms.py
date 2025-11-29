"""Introduce chat rooms and memberships

Revision ID: 20241129_150000
Revises: 20241129_110000
Create Date: 2025-11-29 15:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

# revision identifiers, used by Alembic.
revision = "20241129_150000"
down_revision = "20241129_110000"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "chat_rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_direct", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "chat_room_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_moderator", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("room_id", "user_id", name="uq_room_member"),
    )

    op.add_column("messages", sa.Column("room_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "messages_room_id_fkey",
        "messages",
        "chat_rooms",
        ["room_id"],
        ["id"],
        ondelete="CASCADE",
    )

    conn = op.get_bind()
    org_rows = conn.execute(text("SELECT id FROM organizations")).fetchall()
    room_ids: dict[int, int] = {}

    for row in org_rows:
        org_id = row.id
        result = conn.execute(
            text(
                """
                INSERT INTO chat_rooms (org_id, name, is_system, settings)
                VALUES (:org_id, :name, true, :settings)
                RETURNING id
                """
            ),
            {
                "org_id": org_id,
                "name": "Operations Hub",
                "settings": '{"allow_media": true, "allow_mentions": true, "allow_replies": true}',
            },
        )
        room_ids[org_id] = result.scalar()

    for org_id, room_id in room_ids.items():
        conn.execute(
            text("UPDATE messages SET room_id = :room_id WHERE org_id = :org_id AND room_id IS NULL"),
            {"room_id": room_id, "org_id": org_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO chat_room_members (room_id, user_id, is_moderator, created_at)
                SELECT :room_id, u.id, CASE WHEN u.role IN ('OWNER','ADMIN') THEN true ELSE false END, NOW()
                FROM users u
                WHERE u.org_id = :org_id
                ON CONFLICT DO NOTHING
                """
            ),
            {"room_id": room_id, "org_id": org_id},
        )

    conn.execute(text("UPDATE messages SET room_id = (SELECT id FROM chat_rooms WHERE org_id = messages.org_id AND is_system = true LIMIT 1) WHERE room_id IS NULL"))
    op.alter_column("messages", "room_id", existing_type=sa.Integer(), nullable=False)


def downgrade():
    op.drop_constraint("messages_room_id_fkey", "messages", type_="foreignkey")
    op.drop_column("messages", "room_id")
    op.drop_table("chat_room_members")
    op.drop_table("chat_rooms")
