import json

import pytest
from fastapi import HTTPException

from app import pipeline
from app.models import (
    HarnessAgentTestResult,
    HarnessJob,
    HarnessStep,
    TestCredentials,
)
from app.report import render_markdown
from app.routes.runs import parse_credentials
from tests.test_pipeline import FakeHarness, make_service, wait_terminal, write_apk  # noqa: F401

PASSWORD = "S3cret!pw"
LOGIN = "tester@example.com"
CREDS = TestCredentials(login=LOGIN, password=PASSWORD, note="OTP is 482913", offline_after_login=True)


class LeakyHarness(FakeHarness):
    """A harness that (wrongly) echoes the account everywhere; the API must still never store it."""

    def __init__(self):
        super().__init__()
        self.requests = []

    async def submit(self, apk_path, request):
        self.requests.append(request)
        return await super().submit(apk_path, request)

    async def poll(self, job_id):
        job = await super().poll(job_id)
        return HarnessJob(
            job_id=job.job_id, run_id=job.run_id, status=job.status, current_profile=job.current_profile,
            events=[f"typed {PASSWORD} for {LOGIN}", "line2"],
        )  # fmt: skip

    async def result(self, job_id):
        res = await super().result(job_id)
        step = HarnessStep(index=0, action="fill", target=LOGIN, ok=True, note=f"typed {PASSWORD} otp 482913")
        res.agent_tests = [
            HarnessAgentTestResult(id="offline_after_login", title="Offline", passed=False,
                                   reason=f"login {LOGIN} then {PASSWORD} broke", steps=[step]),
        ]  # fmt: skip
        return res


def test_parse_credentials_validates():
    assert parse_credentials("") is None
    assert parse_credentials(json.dumps({"login": "a", "password": "b"})).password == "b"
    with pytest.raises(HTTPException) as e:
        parse_credentials(json.dumps({"password": "x" * 201}))
    assert e.value.status_code == 422 and "xxx" not in str(e.value.detail)
    with pytest.raises(HTTPException):
        parse_credentials("not json")
    assert PASSWORD not in repr(CREDS)


async def test_credentials_in_memory_only_and_never_stored(make_service, fake_analyzer, tmp_path):  # noqa: F811
    harness = LeakyHarness()
    service = await make_service(harness)
    run = await service.create_run(write_apk(tmp_path), "up.apk", ["baseline"], credentials=CREDS)
    assert pipeline.CREDENTIALS[run.id].password == PASSWORD  # in memory while running
    done = await wait_terminal(service, run.id)
    assert done.status == "done"
    # given to the harness (append-only contract field), dropped once the run is terminal
    assert harness.requests[0].credentials.password == PASSWORD
    for _ in range(50):  # the done-callback runs right after the task ends
        if run.id not in pipeline.CREDENTIALS:
            break
        await __import__("asyncio").sleep(0.01)
    assert run.id not in pipeline.CREDENTIALS
    findings = await service.list_findings(run.id)
    events = await service.list_events(run.id)
    blob = json.dumps(
        [f.model_dump(mode="json") for f in findings]
        + [e.model_dump(mode="json") for e in events]
        + [done.model_dump(mode="json")]
    )
    blob += render_markdown(done, findings, [])
    root = tmp_path / "data"
    for p in root.rglob("*"):
        if p.is_file() and p.name != "app.apk":
            blob += p.read_text("utf-8", "ignore")
    for secret in (PASSWORD, LOGIN, "482913"):
        assert secret not in blob
    assert "***" in blob  # masked, not dropped
    # the agent-test card artifact is masked too
    assert PASSWORD not in (root / "runs" / run.id / "artifacts" / "agent_tests.json").read_text() if (
        root / "runs" / run.id / "artifacts" / "agent_tests.json"
    ).exists() else True


async def test_run_without_credentials_sends_none(make_service, fake_analyzer, tmp_path):  # noqa: F811
    harness = LeakyHarness()
    service = await make_service(harness)
    run = await service.create_run(write_apk(tmp_path), "up.apk", ["baseline"])
    await wait_terminal(service, run.id)
    assert harness.requests[0].credentials is None
