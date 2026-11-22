import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from app import github_import as gh
from app.auth.supabase import bearer_token, verify_token
from app.conversations.store import get_conversation_store
from app.models import Run, TestCredentials
from app.routes.runs import DEFAULT_PROFILES, parse_profiles
from app.services import get_run_service
from app.settings import Settings

router = APIRouter(prefix="/api/runs")


class ImportRequest(BaseModel):
    repo_url: str
    profiles: list[str] | None = None
    credentials: TestCredentials | None = None


@router.post("/import", status_code=201)
async def import_run(
    request: Request, body: ImportRequest, authorization: str | None = Header(default=None)
) -> Run:
    settings: Settings = request.app.state.settings
    user = await verify_token(bearer_token(authorization), settings)
    if user is None and settings.auth_required:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    profile_ids = parse_profiles(",".join(body.profiles) if body.profiles else DEFAULT_PROFILES)
    token = settings.github_token or None

    tmp_dir = settings.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"{uuid.uuid4().hex}.apk"
    try:
        ref = gh.parse_repo_url(body.repo_url)
        async with gh.new_client() as client:
            asset = await gh.find_apk(ref, token, client)
            await gh.download_apk(asset, tmp, token, client)
        service = get_run_service()
        run = await service.create_run(str(tmp), asset.name, profile_ids, credentials=body.credentials)
        await service.bus.publish(
            run.id, "log", f"Imported from github.com/{ref.owner}/{ref.repo} release {asset.release}"
        )
        if user is not None:
            await get_conversation_store().set_run_owner(run.id, user.id)
        return run
    except gh.GithubImportError as e:
        raise HTTPException(e.status, e.detail) from None
    finally:
        tmp.unlink(missing_ok=True)
