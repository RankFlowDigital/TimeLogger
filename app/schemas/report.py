from pydantic import BaseModel


class UserReport(BaseModel):
    user_id: int
    full_name: str
    total_hours: float
    overbreak_minutes: int
    rollcall_minutes: int
    net_hours: float
    sessions_count: int
    rollcall_passed: int
    rollcall_late: int
    rollcall_missed: int
