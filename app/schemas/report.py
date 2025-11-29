from datetime import date

from pydantic import BaseModel


class UserReport(BaseModel):
    user_id: int
    full_name: str
    total_hours: float
    lunch_minutes: int = 0
    break_minutes: int = 0
    overbreak_minutes: int
    rollcall_minutes: int
    net_hours: float
    sessions_count: int
    rollcall_passed: int
    rollcall_late: int
    rollcall_missed: int


class UserReportQuery(BaseModel):
    start_date: date
    end_date: date
