"""f21: deploys must not end runs. Shutdown leaves them alone; startup resumes them (max twice)."""

import asyncio
import subprocess
from pathlib import Path

from tests.conftest import make_apk_bytes, make_run
from tests.test_reliability import ScriptHarness, apk, fast, make_service  # noqa: F401


async def _orphan(service, tmp_path, run_id="old", status="running"):
    path = tmp_path / f"{run_id}.apk"
    path.write_bytes(make_apk_bytes())
    await service.storage.create_run(make_run(run_id, status), str(path))
    return path


async def test_shutdown_leaves_in_progress_runs_untouched(make_service, fake_analyzer, tmp_path):  # noqa: F811
    service = await make_service(ScriptHarness())  # stays "running" forever
    run = await service.create_run(apk(tmp_path), "up.apk", ["budget_2gb"])
    for _ in range(300):
        if (await service.get_run(run.id)).status == "running":
            break
        await asyncio.sleep(0.01)
    await service.shutdown()
    assert (await service.get_run(run.id)).status == "running"
    events = await service.list_events(run.id)
    assert not any(e.type == "error" or (e.data or {}).get("status") in ("cancelled", "failed") for e in events)


async def test_startup_resumes_running_run_with_same_id(make_service, fake_analyzer, tmp_path):  # noqa: F811
    h = ScriptHarness()
    service = await make_service(h)
    await _orphan(service, tmp_path)
    await service.bus.publish("old", "log", "Test phone job started", {"job_id": "jobX"})
    assert await service.recover_orphans() == 1
    await asyncio.sleep(0.3)  # the pipeline is running again for the same run id
    assert "old" in service._tasks
    events = await service.list_events("old")
    assert any(e.message.startswith("The server was updated during this test") for e in events)
    assert h.cancelled
    assert (await service.get_run("old")).status != "failed"
    await service.shutdown()


async def test_startup_resume_is_capped_at_two(make_service, fake_analyzer, tmp_path):  # noqa: F811
    service = await make_service(ScriptHarness())
    await _orphan(service, tmp_path)
    for n in (1, 2):
        await service.bus.publish("old", "log", "resumed", {"resumed": n})
    await service.recover_orphans()
    run = await service.get_run("old")
    assert run.status == "failed" and "server restarted" in run.error


def test_deploy_script_waits_for_active_runs():
    script = Path(__file__).resolve().parents[2] / "deploy" / "deploy_api.sh"
    assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
    text = script.read_text(encoding="utf-8")
    assert text.index("Waiting for") < text.index("systemctl restart bharatbench-api")
