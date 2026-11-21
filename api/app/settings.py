"""Single settings object for the API, read from env / api/.env."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("../data")
    harness_url: str | None = None
    harness_token: str | None = None
    sarvam_api_key: str | None = None
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def harness_configured(self) -> bool:
        return bool(self.harness_url)
