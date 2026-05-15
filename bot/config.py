from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: SecretStr
    database_path: str = "/data/travels.db"
    log_level: str = "INFO"
    log_json: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def db_dsn(self) -> str:
        return f"sqlite+aiosqlite:///{self.database_path}"
