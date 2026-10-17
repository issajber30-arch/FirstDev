# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FIRSTDEV_", extra="ignore")

    env: str = "dev"
    obsidian_log_dir: str | None = None
    database_url: str = "sqlite:///./firstdev.db"
    jwt_secret: SecretStr  # required: no default, so a missing secret fails at startup
    jwt_ttl_minutes: int = 15

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
