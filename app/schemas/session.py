from datetime import datetime

from pydantic import BaseModel, Field


class SessionStart(BaseModel):
    task_description: str | None = Field(default=None, max_length=500)


class SessionSummary(BaseModel):
    work_minutes: int = 0
    lunch_minutes: int = 0
    short_break_minutes: int = 0
    overbreak_minutes: int = 0
    rollcall_deduction_minutes: int = 0
    net_hours: float = 0.0


class SessionRead(BaseModel):
    id: int
    session_type: str
    started_at: datetime
    ended_at: datetime | None

    class Config:
        orm_mode = True
