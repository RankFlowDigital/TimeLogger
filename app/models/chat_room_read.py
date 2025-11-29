from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import relationship

from . import Base


class ChatRoomRead(Base):
    __tablename__ = "chat_room_reads"
    __table_args__ = (UniqueConstraint("room_id", "user_id", name="uq_chat_room_read_member"),)

    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_read_at = Column(DateTime, nullable=False, server_default=func.now())

    room = relationship("ChatRoom", back_populates="reads")
    user = relationship("User")
