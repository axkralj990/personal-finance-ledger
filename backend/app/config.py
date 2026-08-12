from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    data_dir: Path = Field(default=Path("data/runtime"), validation_alias="DATA_DIR")
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, validation_alias="MAX_UPLOAD_BYTES")
    max_file_rows: int = Field(default=20_000, validation_alias="MAX_FILE_ROWS")
    timezone: str = Field(default="Europe/Ljubljana", validation_alias="TIMEZONE")
    frontend_dist_path: Path = Field(
        default=Path("frontend/dist"), validation_alias="FRONTEND_DIST_PATH"
    )
    yahoo_finance_base_url: str = Field(
        default="https://query1.finance.yahoo.com",
        validation_alias="YAHOO_FINANCE_BASE_URL",
    )
    ecb_data_base_url: str = Field(
        default="https://data-api.ecb.europa.eu/service/data",
        validation_alias="ECB_DATA_BASE_URL",
    )
    market_data_timeout_seconds: float = Field(
        default=10.0, validation_alias="MARKET_DATA_TIMEOUT_SECONDS", gt=0, le=60
    )
    quote_preview_max_age_hours: int = Field(
        default=24, validation_alias="QUOTE_PREVIEW_MAX_AGE_HOURS", gt=0, le=168
    )

    @field_validator("max_upload_bytes", "max_file_rows")
    @classmethod
    def positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("limit must be positive")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'finance.sqlite3').resolve()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
