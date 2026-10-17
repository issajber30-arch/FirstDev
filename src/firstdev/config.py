from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FIRSTDEV_", extra="ignore")

    env: str = "dev"
    obsidian_log_dir: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
