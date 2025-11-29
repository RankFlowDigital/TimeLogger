from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, JSON, Text, func

from . import Base

message_type_enum = Enum("CHAT", "SYSTEM", "BROADCAST", "ROLL_CALL", name="message_type")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    message_type = Column(message_type_enum, nullable=False, default="CHAT")
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
