from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    harness_token: str  # required; no default
    device_kind: Literal["redroid", "emulator"] = "redroid"
    android_serial: str = "127.0.0.1:5555"
    tc_path: str = "/usr/sbin/tc"
    ip_path: str = "/usr/sbin/ip"
    sudo_path: str = "sudo"
    jobs_dir: Path = Path("./jobs")
    adb_path: str = "adb"
    maestro_path: str = "maestro"
    job_timeout_s: int = 720
    max_apk_mb: int = 300


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
