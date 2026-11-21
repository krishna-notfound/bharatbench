"""Single settings object for the API, read from env / api/.env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("../data")
    harness_url: str | None = None
    harness_token: str | None = None
    sarvam_api_key: str | None = None
    llm_base_url: str = "https://api.sarvam.ai/v1"
    llm_model: str = "sarvam-105b"
    llm_api_key: str | None = None  # falls back to sarvam_api_key
    auth_required: bool = False
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    storage_backend: Literal["sqlite", "supabase"] = "sqlite"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_key(self) -> str | None:
        return self.llm_api_key or self.sarvam_api_key

    @property
    def harness_configured(self) -> bool:
        return bool(self.harness_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
