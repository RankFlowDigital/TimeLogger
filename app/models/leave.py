from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, func

from . import Base

leave_type_enum = Enum("LEAVE", "DAY_OFF", name="leave_type")


class Leave(Base):
    __tablename__ = "leaves"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    type = Column(leave_type_enum, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
