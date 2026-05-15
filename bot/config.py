from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    anthropic_api_key: SecretStr
    serpapi_key: SecretStr
    database_path: str = "/data/travels.db"
    log_level: str = "INFO"
    log_json: bool = True
    scheduler_tick_seconds: int = 3600
    watch_check_interval_hours: int = 24
    alert_cooldown_hours: int = 12
    haiku_model: str = "claude-haiku-4-5"
    sonnet_model: str = "claude-sonnet-4-6"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def db_dsn(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"
