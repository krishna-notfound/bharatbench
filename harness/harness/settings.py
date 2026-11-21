from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    harness_token: str  # required; no default
    android_serial: str = "emulator-5554"
    jobs_dir: Path = Path("./jobs")
    adb_path: str = "adb"
    maestro_path: str = "maestro"
    job_timeout_s: int = 720
    max_apk_mb: int = 300


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
