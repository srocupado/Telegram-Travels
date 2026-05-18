from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    serpapi_key: SecretStr
    access_password: SecretStr

    ai_provider: Literal["anthropic", "openai", "gemini"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    haiku_model: str = "claude-haiku-4-5"
    sonnet_model: str = "claude-sonnet-4-6"
    openai_fast_model: str = "gpt-5-mini"
    openai_slow_model: str = "gpt-5"
    gemini_fast_model: str = "gemini-2.5-flash"
    gemini_slow_model: str = "gemini-2.5-pro"

    database_path: str = "/data/travels.db"
    log_level: str = "INFO"
    log_json: bool = True
    scheduler_tick_seconds: int = 300
    watch_check_interval_hours: int = 24
    alert_cooldown_hours: int = 12
    congress_digest_enabled: bool = True

    google_maps_api_key: SecretStr | None = None
    home_coords: str | None = None
    work_coords: str | None = None
    route_google_maps_url: str | None = None
    traffic_digest_enabled: bool = True
    traffic_hour: int = 7
    traffic_minute: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def db_dsn(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"
