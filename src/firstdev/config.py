# Copyright (c) 2026 Issa Jber. All rights reserved. FirstDev Platform.
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FIRSTDEV_", extra="ignore")

    env: str = "dev"
    obsidian_log_dir: str | None = None
    database_url: str = "sqlite:///./firstdev.db"
    jwt_secret: SecretStr  # required: no default, so a missing secret fails at startup
    jwt_ttl_minutes: int = 15
    refresh_ttl_days: int = 7
    # Cookies get the Secure flag unless this is false (plain-http localhost development only).
    cookie_secure: bool = True
    cookie_path_prefix: str = ""  # "/api" when served behind the Next.js proxy
    # Real signups need a personal invite code (scripts/invites.py); tests turn this off.
    require_invite: bool = True
    # Shared with the Next.js proxy: only requests carrying it may name the client IP.
    proxy_secret: SecretStr | None = None
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    # "fake" swaps in CannedLLM (no API calls, no cost); refused in prod.
    llm_mode: Literal["real", "fake"] = "real"
    llm_daily_usd: float = 5.0  # global cap across all users and sandboxes, UTC day
    # Cloudflare Turnstile guards sandbox creation. "Disabled" skips the check (dev/tests only).
    turnstile_secret: SecretStr | None = None
    turnstile_disabled: bool = False
    # Where fastembed caches the embedding model (downloaded once, by the worker only).
    model_cache: str = "~/.cache/firstdev/models"
    # Unprefixed env var (shared convention); read-only public-repo token, never logged.
    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")

    @field_validator("jwt_secret")
    @classmethod
    def _secret_long_enough(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("must be at least 32 characters")
        return v

    @model_validator(mode="after")
    def _prod_requirements(self) -> "Settings":
        if self.env == "prod":
            if self.llm_mode == "fake":
                raise ValueError("FIRSTDEV_LLM_MODE=fake is not allowed when env is prod")
            if self.proxy_secret is None or not self.proxy_secret.get_secret_value():
                raise ValueError("FIRSTDEV_PROXY_SECRET is required when env is prod")
            if not self.cookie_secure:
                raise ValueError("FIRSTDEV_COOKIE_SECURE must be true when env is prod")
            if self.turnstile_disabled:
                raise ValueError("FIRSTDEV_TURNSTILE_DISABLED is not allowed when env is prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
