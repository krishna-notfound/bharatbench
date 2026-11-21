# Contract v2 — Realtime voice, users, conversations (frozen 2026-11-21)

Supersedes `contracts/README.md` §5 (voice WS). §1–4 and §6 tools stay valid. Oryn reference repo
(read-only): `D:\Project\ganai-ai-project\dost-ai`. Never copy files from it that hold secrets (`.env*`, `*.pem`).

## 1. Realtime WebSocket — `WS /ws/realtime`

Base protocol = **Oryn protocol v2** exactly as defined in
`dost-ai/backend/app/websocket/protocol.py` and `dost-ai/apps/web/lib/realtime/protocol.ts`
(session.start, input.speech_started/ended, user.text, turn.cancel, playback.*, heartbeat, session.end;
server: session.ready, state, transcript.final, llm.started, text.delta, text.segment, audio.started,
audio.segment (binary frame, 8-byte `>II` header generation_id, seq), audio.segment_done, turn.resume,
audio.completed, turn.completed, turn.cancelled, pipeline.error, heartbeat).
Mic audio: binary 16 kHz mono PCM s16le, 20 ms frames. TTS audio: PCM s16le at the rate given in `audio.started`.

`session.start` payload: `{ token: string | null, conversation_id: string | null, mode: "voice" | "text", language: "auto" | "hi-IN" | "en-IN" }`.
`token` = Supabase access token (guest or Google); null allowed in dev (`AUTH_REQUIRED=false`).
`session.ready` adds `{ conversation_id: string }` (created if null).

**BharatBench additions (server → client JSON):**
- `tool.started` `{ generation_id, call_id, name, label, args }` — `label` is friendly text ("Starting a test").
- `tool.finished` `{ generation_id, call_id, name, ok, summary }`.
- `job.update` `{ run_id, status: RunStatus, message, progress: number | null }` — pushed for every run the
  session started or is watching, independent of turns. Agent narrates `running`/`done`/`failed` only when idle.
- `state` values add `"working"` (a tool is executing).

Rules: tools that start long work return immediately with a run id (async job pattern); the agent never
says a test finished unless a `job.update` with `done` arrived. Max 4 tool rounds per turn, tool timeout 20 s.

## 2. Conversation store (Python, `api/app/conversations/store.py`, owned by f10)

```python
class ConversationStore(Protocol):
    async def create(self, user_id: str | None, mode: str) -> str: ...            # -> conversation_id
    async def get_owner(self, conversation_id: str) -> str | None: ...
    async def append(self, conversation_id: str, role: Literal["user","assistant","tool"], content: str,
                     *, interrupted: bool = False, meta: dict | None = None) -> None: ...
    async def history(self, conversation_id: str, limit: int = 30) -> list[dict]: ...  # oldest→newest {role, content, interrupted, meta, created_at}
def get_conversation_store() -> ConversationStore: ...
```
Auth helper (f10): `api/app/auth/supabase.py` → `async def verify_token(token: str | None) -> AuthUser | None`
where `AuthUser = {id: str, is_anonymous: bool, email: str | None}`.

## 3. REST additions (f10)

| Method | Path | Auth | Returns |
| ------ | ---- | ---- | ------- |
| GET | `/api/conversations` | Bearer | `[{id, mode, created_at, title}]` newest first (own only) |
| GET | `/api/conversations/{id}/messages` | Bearer | `[{role, content, interrupted, meta, created_at}]` |
Runs get `user_id` (nullable); `/api/runs` filters to the caller's runs when a Bearer token is present.

## 4. Web modules

- `web/lib/realtime/**` + `web/lib/audio/**` + `web/public/mic-worklet.js` (f09-client): ported Oryn client stack;
  exports hook `useRealtime()` → `{ state, orbState, getLevel(): number, transcript: Message[], connect(), disconnect(),
  sendText(t), toggleMic(), interrupt(), conversationId, jobs: Record<runId, JobUpdate> }`.
- `web/components/orb/orb.tsx` (f11): `<Orb state size getLevel? showLabel />` keeps the existing `OrbState` union and
  `orbStateFromRun`, `ORB_LABEL` exports (already used across the app) — visual upgraded to Oryn style.
- `web/lib/supabase/**`, `web/components/auth/**` (f10): `getSupabase()`, `useSession()` → `{session, user, signInGuest, signInGoogle, signOut}`,
  `getAccessToken(): Promise<string|null>`.
