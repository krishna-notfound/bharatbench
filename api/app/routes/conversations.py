from fastapi import APIRouter, Header, HTTPException

from app.auth.supabase import AuthUser, bearer_token, verify_token
from app.conversations.store import get_conversation_store

router = APIRouter(prefix="/api/conversations")


async def require_user(authorization: str | None) -> AuthUser:
    user = await verify_token(bearer_token(authorization))
    if user is None:
        raise HTTPException(401, "Sign in required", headers={"WWW-Authenticate": "Bearer"})
    return user


@router.get("")
async def list_conversations(authorization: str | None = Header(default=None)) -> list[dict]:
    user = await require_user(authorization)
    return await get_conversation_store().list_for_user(user.id)


@router.get("/{conversation_id}/messages")
async def list_messages(conversation_id: str, authorization: str | None = Header(default=None)) -> list[dict]:
    user = await require_user(authorization)
    store = get_conversation_store()
    if await store.get_owner(conversation_id) != user.id:
        raise HTTPException(404, "Conversation not found")
    return await store.history(conversation_id, limit=500)
