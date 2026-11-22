# f15 — Oryn-parity voice pipeline, voice-first home, dynamic security tests

**Status:** Built (merged to main; see docs/FEATURE_MAP.md) | **Depends on:** f09, f14 | **Owners:** Sonnet `voice-engine`, Sonnet `voice-home`, Sonnet `harness-security`

## A. voice-engine (server) — owns `api/app/realtime/**`, `api/tests/realtime/**`, `api/app/settings.py` (new provider fields only)
Goal: the server pipeline matches Oryn (`D:\Project\ganai-ai-project\dost-ai\backend\app\` — engine.py, pipeline.py, streams.py,
conversation/stt_link.py, conversation/turns.py, voice/segmenter.py, voice/interruptions.py, voice/latency.py, providers/*) feature by
feature. First write `api/app/realtime/PARITY.md`: a table of every Oryn pipeline feature → BharatBench status → done/changed.
Must-haves:
- Streaming STT over WebSocket while the user speaks (mic frames forwarded live; `commit` on `input.speech_ended`), with reconnect/backoff
  like Oryn `stt_link.py`. Provider order: Gnani Prisma (if `GNANI_API_KEY` set — port Oryn `providers/gnani_prisma.py`) → Sarvam streaming
  STT (verify endpoint/protocol at https://docs.sarvam.ai, curl `https://docs.sarvam.ai/llms.txt`) → Sarvam REST fallback.
- Streaming TTS (first audio fast): Gnani Timbre (if key; port `providers/gnani_timbre.py`, keep-alive pool, account semaphore) → Sarvam
  streaming TTS (verify docs) → REST fallback. Measure and log time-to-first-audio.
- Speculative turn start on final transcript + endpoint grace (Oryn ENDPOINT_GRACE_MS 180 ms), transcript merge if user keeps talking.
- Contest/backchannel logic, heard_text from playback timing (playback.started/finished), interrupted turns recorded with what was heard.
- Warm-up on session.start (TTS/STT connections, history load) and bounded queues/back-pressure as Oryn.
- turn.metrics: ttft, tt-first-audio per turn (Oryn voice/latency.py).
Keep BharatBench additions (tool.*, job.update, WORKING). Tests with providers mocked. Live check with real Sarvam key.

## B. voice-home (web) — owns `web/app/page.tsx`, `web/app/chat/**`, `web/components/welcome/**`, `web/components/voice/**`,
`web/lib/realtime/**`, `web/lib/audio/**`, `web/components/home/**`
- Home page IS the voice agent (Oryn TalkScreen style, ref `dost-ai/apps/web/components/TalkScreen.tsx`, `Captions.tsx`): big orb centered,
  tap orb (or mic button) to start a live voice session; orb state + level ring driven by `useRealtime()`; word-synced captions under the orb;
  controls row (mic/mute, end, open chat, language); job cards appear under captions when tests run; "Test my app" stays as secondary CTA.
  First visit before any interaction shows the friendly hero copy (no "cheap").
- Chat is a separate experience: `/chat` page (full-height thread, text input, tool chips, job cards, history from
  `GET /api/conversations/{id}/messages` when signed in) sharing the same conversation id with voice. The floating drawer becomes a quick
  launcher to `/chat` on other pages (keep `bb:open-agent` working → opens drawer or navigates to /chat on mobile).
- Client parity with Oryn: InterruptionController thresholds (duck 20%, 700 ms cancel, contest verdict), AudioScheduler lead, GenerationGate,
  heartbeat, reconnect + conversation resume, playback.started/finished events (needed for heard_text), mic permission UX.
- Requires sign-in? No — voice works signed out (token null) but uses the token when present.

## C. harness-security — owns `harness/**`, `api/app/analyzer/rules_runtime.py`, `api/app/analyzer/dedupe.py`, `api/tests/analyzer/**`,
`api/app/models.py` (ONLY: add optional `security: list[HarnessSecurityCheck] = []` to `HarnessResult` + the new model), `harness/harness/models.py` mirror.
Dynamic security tests run once per job on the redroid device (rooted: `adb root` works on redroid — verify), after the journeys:
1. Private storage audit: pull `/data/data/<pkg>/shared_prefs/*.xml`, `databases/*` headers, `files/` listing → plaintext tokens/passwords/
   API keys/JWTs/emails/phone numbers (regexes), unencrypted SQLite with sensitive column names, world-readable files.
2. Logcat leak scan: app-PID lines containing secrets/JWT/Bearer/password/OTP/email/phone.
3. Exported component probe: for each exported non-launcher activity/service/receiver from `dumpsys package <pkg>`, launch it with
   `am start -n` / `am startservice` / `am broadcast` without extras → crash (security + reliability), or opens a screen bypassing login
   (screenshot as evidence). Never send destructive intents.
4. Cleartext traffic observed: `tcpdump` on the redroid veth (host side, sudoers NOPASSWD limited to tcpdump with fixed args) during the
   baseline journey → plain HTTP (port 80) requests' Host headers to non-local hosts.
5. Backup/debuggable runtime confirmation: `run-as` works ⇒ debuggable.
Each check → `HarnessSecurityCheck{id, title, passed: bool, severity, evidence: [{kind, ref, excerpt}], note}`; failed checks become
`source="runtime"`, `category="security"` findings with evidence (mask secrets: keep first 4 + last 4 chars). Honest: if a check can't run, `note`
says why, no finding.
Also fix: runtime finding titles must be human (no log timestamps, e.g. "Network errors on Baseline: SocketTimeoutException ×3"); dedupe
identical ANR/crash signatures per profile.
Deploy: update `deploy/setup_harness_ec2.sh` for tcpdump sudoers; after merging the orchestrator restarts the harness.
