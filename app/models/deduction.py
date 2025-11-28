from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Integer, String, func

from . import Base

deduction_type_enum = Enum("OVERBREAK", "ROLLCALL", name="deduction_type")


class Deduction(Base):
    __tablename__ = "deductions"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    type = Column(deduction_type_enum, nullable=False)
    minutes = Column(Integer, nullable=False)
    description = Column(String, nullable=True)
    related_session_id = Column(Integer, ForeignKey("work_sessions.id"), nullable=True)
    related_roll_call_id = Column(Integer, ForeignKey("roll_calls.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
