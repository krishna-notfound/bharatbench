from app.models import AgentTest
from tests.test_pipeline import FakeHarness, make_service, wait_terminal, write_apk  # noqa: F401


class RecordingHarness(FakeHarness):
    def __init__(self):
        super().__init__()
        self.requests = []

    async def submit(self, apk_path, request):
        self.requests.append(request)
        return await super().submit(apk_path, request)


async def test_default_run_sends_no_agent_tests(make_service, fake_analyzer, tmp_path):  # noqa: F811
    harness = RecordingHarness()
    service = await make_service(harness)
    run = await service.create_run(write_apk(tmp_path), "up.apk", ["baseline"])
    await wait_terminal(service, run.id)
    assert harness.requests[0].agent_tests == []


async def test_run_with_explicit_agent_tests_sends_them(make_service, fake_analyzer, tmp_path):  # noqa: F811
    harness = RecordingHarness()
    service = await make_service(harness)
    tests = [AgentTest(id="bad", title="Wrong email", goal="g", success_check="s")]
    run = await service.create_run(write_apk(tmp_path), "up.apk", ["baseline"], None, tests)
    await wait_terminal(service, run.id)
    assert [t.id for t in harness.requests[0].agent_tests] == ["bad"]
