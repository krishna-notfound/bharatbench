"""Harness HTTP API (runs on the device host only; contracts/README.md section 4).

Invariants (tests: harness/tests/test_api_jobs.py, test_live.py, test_heal.py):
- Binds 127.0.0.1 in deployment; every route requires X-Harness-Token, compared with hmac.compare_digest.
- One job at a time: POST /jobs returns 409 while a job runs (jobs.py owns the device).
- Job ids must be 32-hex and artifact paths must resolve inside the job directory; anything else is rejected.
- adb and host tools are invoked with argument lists only (never shell=True); the API host never runs the APK.
"""
import hmac
import re
import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import ValidationError

from .adb import Adb, Runner, subprocess_runner
from .jobs import Busy, JobRunner
from .models import HarnessJob, HarnessJobRequest, HarnessResult
from .settings import Settings, load_settings

JOB_ID = re.compile(r"[0-9a-f]{32}")
PACKAGE = re.compile(r"[A-Za-z][\w]*(\.[A-Za-z][\w]*)+")


def create_app(settings: Settings | None = None, runner: Runner = subprocess_runner) -> FastAPI:
    settings = settings or load_settings()
    adb = Adb(settings.adb_path, settings.android_serial, runner)
    jobs = JobRunner(settings, adb)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)

    def require_token(x_harness_token: str | None = Header(default=None)) -> None:
        supplied = (x_harness_token or "").encode()
        if not hmac.compare_digest(supplied, settings.harness_token.encode()):
            raise HTTPException(status_code=401, detail="invalid or missing X-Harness-Token")

    app = FastAPI(title="BharatBench harness", dependencies=[Depends(require_token)])
    app.state.jobs = jobs

    def get_job(job_id: str) -> HarnessJob:
        job = jobs.jobs.get(job_id) if JOB_ID.fullmatch(job_id) else None
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    @app.get("/health")
    async def health() -> dict[str, object]:
        return await jobs.health(shutil.which(settings.maestro_path) is not None)

    @app.post("/jobs", status_code=202)
    async def create_job(apk: UploadFile = File(), request: str = Form()) -> HarnessJob:
        try:
            req = HarnessJobRequest.model_validate_json(request)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"invalid request: {exc.errors()[0]['msg']}") from exc
        if not PACKAGE.fullmatch(req.package_name):
            raise HTTPException(status_code=422, detail="invalid package_name")
        if not 1 <= req.journey_steps <= 30:
            raise HTTPException(status_code=422, detail="journey_steps must be 1..30")
        health = await jobs.health(False)
        if not health["adb"]:
            raise HTTPException(status_code=503, detail="adb is not available on the test lab host")
        try:
            job, job_dir = jobs.start(req)
        except Busy as exc:
            raise HTTPException(status_code=409, detail="a job is already running") from exc
        limit = settings.max_apk_mb * 1024 * 1024
        written = 0
        try:
            with (job_dir / "app.apk").open("wb") as fh:
                while chunk := await apk.read(1024 * 1024):
                    written += len(chunk)
                    if written > limit:
                        raise HTTPException(status_code=413, detail="apk too large")
                    fh.write(chunk)
        except BaseException:
            jobs.abort_start(job)
            raise
        jobs.launch(job, req)
        return job

    @app.get("/jobs/{job_id}")
    async def read_job(job_id: str) -> HarnessJob:
        return get_job(job_id)

    @app.get("/jobs/{job_id}/result")
    async def read_result(job_id: str) -> HarnessResult:
        job = get_job(job_id)
        result = jobs.results.get(job.job_id)
        if job.status in ("queued", "running") or result is None:
            raise HTTPException(status_code=409, detail=f"job is {job.status}")
        return result

    @app.get("/jobs/{job_id}/live")
    async def live(job_id: str) -> dict[str, object]:
        get_job(job_id)
        state = jobs.live.get(job_id)
        if state is None:
            return {"seq": 0, "running": False, "has_frame": False, "tap": None, "screen": None}
        return state.public()

    @app.get("/jobs/{job_id}/live.png")
    async def live_png(job_id: str) -> Response:
        get_job(job_id)
        state = jobs.live.get(job_id)
        if state is None or state.frame is None:
            raise HTTPException(status_code=404, detail="no frame yet")
        return Response(state.frame, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/jobs/{job_id}/artifacts/{path:path}")
    async def artifact(job_id: str, path: str) -> FileResponse:
        get_job(job_id)
        base = jobs.job_dir(job_id).resolve()
        target = (base / path).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(Path(target))

    @app.post("/jobs/{job_id}/cancel")
    async def cancel(job_id: str) -> HarnessJob:
        get_job(job_id)
        job = jobs.cancel(job_id)
        assert job is not None
        return job

    @app.delete("/jobs/{job_id}")
    async def delete_job(job_id: str) -> dict[str, object]:
        if not JOB_ID.fullmatch(job_id):
            raise HTTPException(status_code=404, detail="job not found")
        if not jobs.delete(job_id):
            raise HTTPException(status_code=409, detail="job is still running")
        return {"deleted": True, "job_id": job_id}

    return app


app = create_app()
