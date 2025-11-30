from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Fundamental Ecom LLC"
    secret_key: str = "change-me"
    session_cookie: str = "team_monitor_session"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/team_monitor"
    environment: str = "development"
    rollcall_tick_token: str | None = None
    smtp_host: str | None = Field(default=None, alias="MAIL_SMTP_HOST")
    smtp_port: int = Field(default=587, alias="MAIL_SMTP_PORT")
    smtp_username: str | None = Field(default=None, alias="MAIL_SMTP_USERNAME")
    smtp_password: str | None = Field(default=None, alias="MAIL_SMTP_PASSWORD")
    smtp_from: str | None = Field(default=None, alias="MAIL_SENDER_ADDRESS")
    smtp_from_name: str | None = Field(default=None, alias="MAIL_SENDER_NAME")
    smtp_use_tls: bool = Field(default=True, alias="MAIL_SMTP_TLS")
    smtp_use_ssl: bool = Field(default=False, alias="MAIL_SMTP_SSL")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
