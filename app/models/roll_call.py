from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, func

from . import Base

rollcall_result_enum = Enum("PENDING", "PASSED", "LATE", "MISSED", name="rollcall_result")


class RollCall(Base):
    __tablename__ = "roll_calls"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    triggered_at = Column(DateTime, nullable=False)
    deadline_at = Column(DateTime, nullable=False)
    responded_at = Column(DateTime, nullable=True)
    result = Column(rollcall_result_enum, nullable=False, default="PENDING")
    response_delay_seconds = Column(Integer, nullable=True)
