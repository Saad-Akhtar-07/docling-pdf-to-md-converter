"""apps/api settings, loaded from env via pydantic-settings.

Deliberately does NOT include DATABASE_URL: packages/persistence/db.py is
already the one place that resolves that (see its own .env.local/.env
loading), and duplicating it here would just be a second source of truth to
drift out of sync with.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    upload_dir: Path = _REPO_ROOT / "data" / "uploads"
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(
        env_prefix="API_",
        env_file=[str(_REPO_ROOT / ".env.local"), str(_REPO_ROOT / ".env")],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
