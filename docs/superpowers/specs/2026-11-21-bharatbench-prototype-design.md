# BharatBench Prototype — Design (approved 2026-11-21)

## Intent
HackFront 2026 demo in ~1 hour of build: a real (not mocked) Android reliability platform — upload APK →
static security/perf scan → runtime test on an EC2 emulator under cheap-phone profiles → impact-ranked
findings with evidence + Maestro repro → Sarvam voice agent that starts tests and explains findings.

## Goals / Non-goals / Anti-goals
- Goals: real evidence, honest fidelity labels, working end-to-end demo, voice that performs real actions.
- Non-goals: GitHub builds, Supabase (later, teammate), Resend, auth, multi-device.
- Anti-goals: fabricated results; claiming thermal/CPU simulation; agent with shell access; public harness port.

## Approaches considered
1. **Chosen — monorepo: Next.js web + FastAPI api (pipeline, analyzer, voice) + separate FastAPI harness on EC2 via SSH tunnel.**
   Clean seam for the emulator; the api is fully demoable without it (static scan); voice reuses the same RunService.
2. Everything on EC2 in one process — simpler deploy but couples untrusted-APK device work with API + secrets; rejected.
3. Agent framework (LangGraph etc.) for voice — adds a dependency for 7 tools; custom loop gives direct control over cancellation/barge-in; rejected.
4. GitHub repo → Gradle build input — too risky in the time; deferred (user chose APK-only).

## Decided (by user)
Next.js web (not Expo); full voice agent now; EC2 emulator (user provides IP + pem in `secrets/`); APK upload only;
all four check types (static security, perf/size, runtime cheap-phone, impact ranking + repro); Supabase later.

## Design
See `context/architecture-context.md`, `contracts/README.md`, `api/app/models.py`, `api/app/profiles.py`, and
feature specs f02–f06. Orchestrator calls (marked as mine): SQLite behind Storage interface; harness token + 127.0.0.1;
runtime skipped not faked; impact weights/prevalence in `profiles.py`/`scoring.py` as labelled assumptions.

## Left to builders
Exact UI composition within `ui-context.md`; Sarvam endpoint specifics (verified from docs in f05 step 0);
crawler heuristics details within f04 rules.
