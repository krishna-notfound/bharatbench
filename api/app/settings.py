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
    # f15 realtime providers. Sarvam streaming is primary; REST is the fallback.
    sarvam_stream_stt: bool = True
    sarvam_stream_tts: bool = True
    endpoint_grace_ms: int = 700  # speculative turn audio gate; 180 ms (Oryn) cut users off mid-sentence
    contest_timeout_s: float = 3.0
    # Gnani Prisma STT is implemented but inert unless GNANI_API_KEY is set. (Timbre TTS: not used.)
    gnani_api_key: str | None = None
    gnani_stt_ws_url: str = "wss://api.vachana.ai/stt/v3/stream"
    gnani_stt_model: str = "prisma-v3.0"
    gnani_stt_format: str = "codemix"
    auth_required: bool = False
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_jwt_secret: str | None = None
    storage_backend: Literal["sqlite", "supabase"] = "sqlite"
    github_token: str | None = None  # optional: private repos / higher rate limit. Never logged.
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
