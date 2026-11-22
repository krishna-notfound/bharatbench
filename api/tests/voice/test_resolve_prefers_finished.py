from voice_fakes import FakeRunService, make_run

from app.voice.tools import ToolContext, _resolve_run


async def test_apk_name_resolves_to_newest_finished_run_not_in_progress_one():
    svc = FakeRunService()
    svc.runs = [make_run("running1", status="running"), make_run("done1", status="done")]  # newest first
    run = await _resolve_run(svc, "demo.apk", ToolContext())
    assert run is not None and run.id == "done1"


async def test_falls_back_to_in_progress_when_nothing_finished():
    svc = FakeRunService()
    svc.runs = [make_run("running1", status="running"), make_run("failed1", status="failed")]
    run = await _resolve_run(svc, "demo", ToolContext())
    assert run is not None and run.id == "running1"
