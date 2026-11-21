"""Shared fakes for voice tests: a fake RunService and Sarvam mock helpers."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from typing import Any, Self

from app.models import Evidence, Finding, Impact, ProfileId, Run, RunEvent, RunSummary

NOW = datetime(2026, 11, 21, tzinfo=UTC)
SARVAM = "https://api.sarvam.ai"
WAV_B64 = base64.b64encode(b"RIFFfakewav").decode()


def make_run(run_id: str = "run1", status: str = "done") -> Run:
    return Run(
        id=run_id,
        apk_name="demo.apk",
        status=status,  # type: ignore[arg-type]
        profile_ids=["baseline"],
        created_at=NOW,
        updated_at=NOW,
        summary=RunSummary(
            counts={"critical": 2, "high": 0, "medium": 0, "low": 0}, total_findings=2, reliability_score=61.0
        ),
    )


def make_finding(fid: str, score: float, severity: str = "high", run_id: str = "run1") -> Finding:
    return Finding(
        id=fid,
        run_id=run_id,
        source="static",
        category="security",
        rule_id="sec.debuggable",
        title=f"Finding {fid}",
        severity=severity,  # type: ignore[arg-type]
        description="d",
        evidence=[Evidence(kind="note", excerpt="x" * 500)],
        impact=Impact(users_exposed=0.5, severity_weight=0.5, flow_usage=0.5, score=score),
    )


class FakeSubscription:
    def __init__(self, events: list[RunEvent]) -> None:
        self._events = list(events)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __aiter__(self) -> FakeSubscription:
        return self

    async def __anext__(self) -> RunEvent:
        if not self._events:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self._events.pop(0)


class FakeRunService:
    def __init__(self) -> None:
        self.runs = [make_run("run1")]
        self.findings = [make_finding("f1", 10.0), make_finding("f2", 40.0, "critical")]
        self.rerun_calls: list[tuple[str, list[ProfileId]]] = []
        self.rerun_steps: list[int | None] = []
        self.cancel_calls: list[str] = []
        self.events: list[RunEvent] = []

    async def create_run(self, apk_path: str, apk_name: str, profile_ids: list[ProfileId]) -> Run:
        raise NotImplementedError

    async def rerun(
        self, source_run_id: str, profile_ids: list[ProfileId], journey_steps: int | None = None
    ) -> Run:
        self.rerun_calls.append((source_run_id, profile_ids))
        self.rerun_steps.append(journey_steps)
        run = make_run("run2", "queued")
        self.runs.insert(0, run)
        return run

    async def get_run(self, run_id: str) -> Run | None:
        return next((r for r in self.runs if r.id == run_id), None)

    async def list_runs(self) -> list[Run]:
        return list(self.runs)

    async def list_findings(self, run_id: str) -> list[Finding]:
        return [f for f in self.findings if f.run_id == run_id]

    async def list_events(self, run_id: str, after_seq: int = 0) -> list[RunEvent]:
        return [e for e in self.events if e.run_id == run_id and e.seq > after_seq]

    async def cancel_run(self, run_id: str) -> Run | None:
        self.cancel_calls.append(run_id)
        run = await self.get_run(run_id)
        return run.model_copy(update={"status": "cancelled"}) if run else None

    def subscribe(self, run_id: str) -> FakeSubscription:
        return FakeSubscription([e for e in self.events if e.run_id == run_id])


def status_event(run_id: str, seq: int, status: str) -> RunEvent:
    return RunEvent(run_id=run_id, seq=seq, ts=NOW, type="status", message=status, data={"status": status})


def chat_reply(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def tool_call(name: str, args: str, call_id: str = "call-1") -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}
