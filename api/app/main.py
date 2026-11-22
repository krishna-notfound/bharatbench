"""FastAPI app factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.events import EventBus
from app.harness_client import HarnessClient
from app.pipeline import HarnessLike
from app.routes import health, runs, ws_runs
from app.services import RunServiceImpl, set_run_service
from app.settings import Settings
from app.storage.base import Storage
from app.storage.sqlite import SqliteStorage
from app.storage.supabase import SupabaseStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    def harness_factory() -> HarnessLike | None:
        if not settings.harness_configured:
            return None
        return HarnessClient(settings.harness_url or "", settings.harness_token)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        storage: Storage
        if settings.storage_backend == "supabase":
            if not settings.supabase_url or not settings.supabase_service_role_key:
                raise RuntimeError(
                    "STORAGE_BACKEND=supabase requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"
                )
            storage = SupabaseStorage(settings.supabase_url, settings.supabase_service_role_key)
        else:
            storage = SqliteStorage(settings.data_dir / "bharatbench.db")
        await storage.init()
        service = RunServiceImpl(storage, EventBus(storage), settings.data_dir, harness_factory)
        await service.recover_orphans()
        service.start_watchdog()
        set_run_service(service)
        app.state.service = service
        try:
            yield
        finally:
            await service.shutdown()
            set_run_service(None)
            await storage.close()

    app = FastAPI(title="BharatBench API", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    try:
        from app.routes.imports import router as imports_router
    except ImportError:
        imports_router = None
    if imports_router is not None:  # before runs so /api/runs/import is never shadowed by /{run_id}
        app.include_router(imports_router)
    app.include_router(runs.router)
    app.include_router(ws_runs.router)
    try:
        from app.routes.insights import router as insights_router
    except ImportError:  # f20 insights not present
        insights_router = None
    if insights_router is not None:
        app.include_router(insights_router)
    try:
        from app.voice.router import router as voice_router
    except ImportError:  # f05 not merged yet
        voice_router = None
    try:
        from app.routes.conversations import router as conversations_router
    except ImportError:
        conversations_router = None
    if conversations_router is not None:
        app.include_router(conversations_router)
    if voice_router is not None:
        app.include_router(voice_router)
    try:
        from app.realtime.router import router as realtime_router
    except ImportError:  # f09 realtime engine not present
        realtime_router = None
    if realtime_router is not None:
        app.include_router(realtime_router)
    return app


app = create_app()
