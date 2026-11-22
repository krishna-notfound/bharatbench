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
    tcpdump_path: str = "/usr/bin/tcpdump"
    timeout_path: str = "/usr/bin/timeout"
    security_enabled: bool = True
    security_timeout_s: int = 150
    jobs_dir: Path = Path("./jobs")
    adb_path: str = "adb"
    maestro_path: str = "maestro"
    job_timeout_s: int = 720
    profile_timeout_s: int = 300  # one profile hanging longer than this is treated as a device problem
    docker_path: str = "docker"
    container_name: str = "redroid"
    min_free_mb: int = 600  # health gate: below this the lab frees space before running
    hard_min_free_mb: int = 300  # below this even after cleanup, the job is refused
    boot_timeout_s: int = 120
    reconnect_wait_s: int = 20
    keep_jobs: int = 5
    max_apk_mb: int = 300


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
