from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Team Monitor"
    secret_key: str = "change-me"
    session_cookie: str = "team_monitor_session"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/team_monitor"
    environment: str = "development"
    rollcall_tick_token: str | None = None

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
