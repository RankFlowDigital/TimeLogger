from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, func

from . import Base

session_type_enum = Enum("WORK", "LUNCH", "SHORT_BREAK", name="session_type")


class WorkSession(Base):
    __tablename__ = "work_sessions"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    task_description = Column(Text, nullable=True)
    session_type = Column(session_type_enum, nullable=False, default="WORK")
    source = Column(String, nullable=True)
