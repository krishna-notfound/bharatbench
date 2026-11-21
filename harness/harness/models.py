"""Copy of the harness section of api/app/models.py. Keep JSON-compatible; do not diverge."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ProfileId = Literal[
    "baseline", "budget_2gb", "flaky_network", "low_storage", "battery_saver", "process_death"
]


HarnessJobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


class HarnessJobRequest(BaseModel):
    run_id: str
    package_name: str
    main_activity: str | None = None
    profiles: list[ProfileId]
    journey_steps: int = 8


class HarnessCrash(BaseModel):
    type: Literal["crash", "anr", "native_crash"]
    excerpt: str


class HarnessScreen(BaseModel):
    index: int  # 0 = after launch
    screenshot: str | None = None  # artifact path
    ui_dump: str | None = None  # artifact path
    activity: str | None = None
    note: str | None = None


class HarnessStep(BaseModel):
    index: int
    action: Literal["launch", "tap", "back", "background", "kill", "restore", "wait", "toggle_network"]
    target: str | None = None  # text/resource-id/"x,y"
    ok: bool
    duration_ms: int | None = None
    note: str | None = None


class HarnessProfileResult(BaseModel):
    profile_id: ProfileId
    applied: bool
    apply_note: str | None = None  # what was actually done, or why it could not be applied
    launched: bool
    launch_ms: int | None = None
    crashes: list[HarnessCrash] = []
    network_errors: list[str] = []
    stuck_loading: bool = False  # same screen with progress indicator for >= 15s
    state_lost_after_restore: bool | None = None  # process_death only
    screens: list[HarnessScreen] = []
    steps: list[HarnessStep] = []
    maestro_flow: str | None = None
    memory_pss_kb: int | None = None
    logcat: str | None = None  # artifact path


class HarnessJob(BaseModel):
    job_id: str
    run_id: str
    status: HarnessJobStatus
    current_profile: ProfileId | None = None
    progress: float = 0.0
    events: list[str] = []  # human-readable progress lines, append-only
    error: str | None = None


class HarnessResult(BaseModel):
    job_id: str
    device: str
    android_version: str | None = None
    profiles: list[HarnessProfileResult]
