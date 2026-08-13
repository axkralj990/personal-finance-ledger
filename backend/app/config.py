from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    data_dir: Path = Field(validation_alias="DATA_DIR")
    database_url: str | None = Field(default=None, validation_alias="DATABASE_URL")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, validation_alias="MAX_UPLOAD_BYTES")
    max_file_rows: int = Field(default=20_000, validation_alias="MAX_FILE_ROWS")
    timezone: str = Field(default="Europe/Ljubljana", validation_alias="TIMEZONE")
    frontend_dist_path: Path = Field(
        default=Path("frontend/dist"), validation_alias="FRONTEND_DIST_PATH"
    )
    allowed_hosts_setting: str = Field(
        default="testserver,localhost,127.0.0.1,::1",
        validation_alias="ALLOWED_HOSTS",
        exclude=True,
    )
    allowed_origins_setting: str = Field(
        default=(
            "http://testserver,http://localhost,http://localhost:5173,http://localhost:8000,"
            "http://127.0.0.1,http://127.0.0.1:5173,http://127.0.0.1:8000,"
            "https://localhost,https://127.0.0.1"
        ),
        validation_alias="ALLOWED_ORIGINS",
        exclude=True,
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
    openai_mapping_enabled: bool = Field(default=False, validation_alias="OPENAI_MAPPING_ENABLED")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_mapping_model: str = Field(
        default="gpt-4.1-mini", validation_alias="OPENAI_MAPPING_MODEL", min_length=1
    )
    openai_mapping_connect_timeout_seconds: float = Field(
        default=5.0,
        validation_alias="OPENAI_MAPPING_CONNECT_TIMEOUT_SECONDS",
        gt=0,
        le=30,
    )
    openai_mapping_read_timeout_seconds: float = Field(
        default=20.0,
        validation_alias="OPENAI_MAPPING_READ_TIMEOUT_SECONDS",
        gt=0,
        le=60,
    )
    openai_mapping_overall_timeout_seconds: float = Field(
        default=30.0,
        validation_alias="OPENAI_MAPPING_OVERALL_TIMEOUT_SECONDS",
        gt=0,
        le=120,
    )
    openai_mapping_max_retries: int = Field(
        default=1, validation_alias="OPENAI_MAPPING_MAX_RETRIES", ge=0, le=3
    )
    openai_mapping_max_concurrent: int = Field(
        default=1, validation_alias="OPENAI_MAPPING_MAX_CONCURRENT", ge=1, le=1
    )
    openai_mapping_requests_per_hour: int = Field(
        default=10, validation_alias="OPENAI_MAPPING_REQUESTS_PER_HOUR", ge=1, le=10
    )

    @field_validator("max_upload_bytes", "max_file_rows")
    @classmethod
    def positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("limit must be positive")
        return value

    @field_validator("data_dir")
    @classmethod
    def absolute_data_dir(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("DATA_DIR must be absolute")
        return value

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def blank_openai_key_is_unconfigured(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
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

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        return self._split_setting(self.allowed_hosts_setting)

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return self._split_setting(self.allowed_origins_setting)

    @staticmethod
    def _split_setting(value: str) -> tuple[str, ...]:
        return tuple(item.strip() for item in value.split(",") if item.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
