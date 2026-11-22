"""Frozen shared contracts for the BharatBench API.

Mirrored in web/lib/types.ts and contracts/README.md. Changing anything here is a contract change:
stop and get the orchestrator's approval first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low"]
Category = Literal["security", "performance", "reliability", "network", "storage", "memory"]
FindingSource = Literal["static", "runtime"]
EvidenceKind = Literal["logcat", "screenshot", "ui_dump", "manifest", "code", "metric", "note"]
Fidelity = Literal["controlled", "approximated", "unsupported"]
RunStatus = Literal[
    "queued", "analyzing", "provisioning", "running", "scoring", "done", "failed", "cancelled"
]
EventType = Literal["status", "log", "step", "finding", "artifact", "done", "error"]

ProfileId = Literal[
    "baseline", "budget_2gb", "flaky_network", "low_storage", "battery_saver", "process_death"
]


class Profile(BaseModel):
    id: ProfileId
    name: str
    description: str
    fidelity: Fidelity
    how: str  # exact mechanism used by the harness, shown to users verbatim
    users_exposed: float = Field(ge=0, le=1)  # share of target users who face this condition


class Evidence(BaseModel):
    kind: EvidenceKind
    ref: str | None = None  # artifact path relative to the run's artifact dir, if any
    excerpt: str | None = None  # short inline text (log lines, manifest snippet, metric)


class Impact(BaseModel):
    users_exposed: float = Field(ge=0, le=1)
    severity_weight: float = Field(ge=0, le=1)
    flow_usage: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=100)  # 100 * users_exposed * severity_weight * flow_usage


class Finding(BaseModel):
    id: str
    run_id: str
    source: FindingSource
    category: Category
    rule_id: str  # stable machine id, e.g. "sec.debuggable", "rt.crash"
    title: str
    severity: Severity
    description: str
    evidence: list[Evidence] = []
    repro_steps: list[str] = []
    repro_flow: str | None = None  # Maestro YAML
    affected_journey: str | None = None
    journey_step: int | None = None  # 0 = app launch
    profile_id: ProfileId | None = None
    probable_cause: str | None = None
    suggested_fix: str | None = None
    impact: Impact | None = None  # filled by scoring


class AppInfo(BaseModel):
    package_name: str
    app_name: str | None = None
    version_name: str | None = None
    version_code: str | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None
    size_bytes: int
    permissions: list[str] = []
    main_activity: str | None = None
    native_abis: list[str] = []
    dex_count: int = 0
    activities: list[str] = []  # f23: activity class names (for agent test writing)
    ui_strings: list[str] = []  # f23: sample of human-readable strings found in the APK


class RunSummary(BaseModel):
    counts: dict[Severity, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    total_findings: int = 0
    reliability_score: float = 100.0  # 100 - min(100, sum of impact scores)
    runtime_executed: bool = False
    runtime_skipped_reason: str | None = None


class Run(BaseModel):
    id: str
    apk_name: str
    status: RunStatus
    profile_ids: list[ProfileId]
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    app: AppInfo | None = None
    summary: RunSummary | None = None


class RunEvent(BaseModel):
    run_id: str
    seq: int
    ts: datetime
    type: EventType
    message: str
    data: dict[str, Any] | None = None


# ---------- Harness contract (api <-> harness service on EC2) ----------

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


# ---------- Service interface the voice agent (and routes) depend on ----------


class RunService(Protocol):
    async def create_run(self, apk_path: str, apk_name: str, profile_ids: list[ProfileId]) -> Run: ...
    async def rerun(
        self,
        source_run_id: str,
        profile_ids: list[ProfileId],
        journey_steps: int | None = None,
        agent_tests: list[AgentTest] | None = None,
    ) -> Run: ...
    async def get_run(self, run_id: str) -> Run | None: ...
    async def list_runs(self) -> list[Run]: ...
    async def list_findings(self, run_id: str) -> list[Finding]: ...
    async def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]: ...
    async def cancel_run(self, run_id: str) -> Run | None: ...
    def subscribe(self, run_id: str) -> EventSubscription: ...


class EventSubscription(Protocol):
    async def __aenter__(self) -> EventSubscription: ...  # noqa: PYI034
    async def __aexit__(self, *exc: object) -> None: ...
    def __aiter__(self) -> EventSubscription: ...
    async def __anext__(self) -> RunEvent: ...
