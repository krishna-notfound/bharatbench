"""Copy of the harness section of api/app/models.py. Keep JSON-compatible; do not diverge."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ProfileId = Literal[
    "baseline", "budget_2gb", "flaky_network", "low_storage", "battery_saver", "process_death"
]


HarnessJobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


class AgentTest(BaseModel):
    """An app-specific test written by the LLM agent (f23). `condition` must be a supported profile."""

    id: str
    title: str
    goal: str
    condition: ProfileId = "baseline"
    success_check: str


class HarnessJobRequest(BaseModel):
    run_id: str
    package_name: str
    main_activity: str | None = None
    profiles: list[ProfileId]
    journey_steps: int = 8
    agent_tests: list[AgentTest] = []  # f23, optional


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
    action: Literal["launch", "tap", "back", "background", "kill", "restore", "wait", "toggle_network", "fill"]
    target: str | None = None  # text/resource-id/"x,y"
    ok: bool
    duration_ms: int | None = None
    note: str | None = None
    x: int | None = None  # tap point in device pixels (tap steps only)
    y: int | None = None
    screen: int | None = None  # index into `screens` captured right after this step


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


class HarnessAgentTestResult(BaseModel):
    id: str
    title: str
    condition: ProfileId = "baseline"
    passed: bool | None = None  # None = could not be judged (skipped, device problem, no verdict)
    reason: str = ""
    steps: list[HarnessStep] = []
    screens: list[HarnessScreen] = []


class HarnessSecurityEvidence(BaseModel):
    kind: Literal["logcat", "screenshot", "ui_dump", "manifest", "code", "metric", "note"]
    ref: str | None = None  # artifact path relative to the job dir
    excerpt: str | None = None  # secrets masked: first 4 + last 4 chars only


class HarnessSecurityCheck(BaseModel):
    id: str  # e.g. "sec.storage_secrets"
    title: str
    passed: bool = True
    ran: bool = True  # False: the check could not run; `note` says why and no finding is produced
    severity: Literal["critical", "high", "medium", "low"] = "low"
    evidence: list[HarnessSecurityEvidence] = []
    note: str | None = None


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
    security: list[HarnessSecurityCheck] = []
    agent_tests: list[HarnessAgentTestResult] = []  # f23, optional
