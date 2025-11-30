from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String, Time, UniqueConstraint, func
from sqlalchemy.orm import relationship

from . import Base


class ShiftTemplate(Base):
    __tablename__ = "shift_templates"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    name = Column(String(120), nullable=True)
    day_of_week = Column(Integer, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    timezone = Column(String(64), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    assignments = relationship("ShiftAssignment", back_populates="shift", cascade="all, delete-orphan")


class ShiftAssignment(Base):
    __tablename__ = "shift_assignments"
    __table_args__ = (
        UniqueConstraint("shift_id", "user_id", "effective_from", name="uq_shift_assignment_start"),
    )

    id = Column(Integer, primary_key=True)
    shift_id = Column(Integer, ForeignKey("shift_templates.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    shift = relationship("ShiftTemplate", back_populates="assignments")
    user = relationship("User")
