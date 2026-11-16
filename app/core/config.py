from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Only good enough for a laptop. Startup is refused if this is still set in production.
DEV_SECRET_KEY = "dev-secret-change-me-before-deploying-anywhere"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AssetDesk"
    app_version: str = "1.0.0"
    app_env: Literal["development", "test", "production"] = "development"

    database_url: str = "sqlite:///./assetdesk.db"

    secret_key: str = DEV_SECRET_KEY
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=1440)
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://localhost:5173"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Accounts created by app/init_db.py when they don't exist yet
    admin_username: str = "admin"
    admin_password: str = "admin-dev-password"
    staff_username: str = "staff"
    staff_password: str = "staff-dev-password"

    # Stubs for the external systems (sections 5 and 6)
    notifier_delay_seconds: float = Field(default=0.5, ge=0)
    warranty_delay_seconds: float = Field(default=0.5, ge=0)
    warranty_timeout_seconds: float = Field(default=3.0, gt=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def check_production_secrets(self) -> "Settings":
        if self.app_env == "production":
            if self.secret_key == DEV_SECRET_KEY or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be set to a random value of 32+ characters in production")
            if "*" in self.cors_origins:
                raise ValueError("CORS_ORIGINS cannot be '*' in production")
            fields = type(self).model_fields
            defaults = {fields["admin_password"].default, fields["staff_password"].default}
            if {self.admin_password, self.staff_password} & defaults:
                raise ValueError("ADMIN_PASSWORD and STAFF_PASSWORD must be changed in production")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
