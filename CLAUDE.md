# BharatBench — Claude Code Instructions

> The Cheap Phone Test: upload an Android APK, BharatBench runs it on a constrained Android emulator
> (2 GB RAM, slow/flaky network, low storage, battery saver, process death), scans it for security
> and performance issues, ranks findings by real-world user impact, and explains them by voice.

HackFront 2026 · Team BrahMoss. This file is loaded into every session. **Read it fully, then follow
the session start protocol.**

## 1. Session Start Protocol (do this first, every session)

1. Read the context files **in this order**:
   1. `context/project-overview.md` — product, goals, scope, success criteria
   2. `context/architecture-context.md` — stack, boundaries, data model, invariants
   3. `context/ui-context.md` — theme, tokens, typography, component conventions
   4. `context/code-standards.md` — implementation rules
   5. `context/ai-workflow-rules.md` — how work is scoped, split, verified, delivered
   6. `context/progress-tracker.md` — **current state**, done, next, open questions
2. Read `contracts/README.md` (frozen API / WebSocket / harness / voice contracts).
3. Open `features/README.md`. Then read **only** the feature file(s) for the task at hand.
4. Obey `context/AGENTS.md` (Next.js version warning).
5. State in one or two sentences what you understand the current task and phase to be before changing anything.

## 2. Source of Truth Hierarchy

1. The user's latest explicit instruction in this session
2. `features/fNN_*.md` for the feature being built
3. `contracts/README.md`, `api/app/models.py`, `api/app/profiles.py` (frozen contracts)
4. `context/*.md`
5. Code that already exists in the repo
6. Your own memory or training data (**lowest — never overrides the above**)

## 3. Anti-Hallucination Rules

- **Never invent** product behavior, API shapes, table/column names, env var names, package
  versions, or library APIs. If it is not in the context/feature/contract files or verified in the repo, it is unknown.
- **Verify before you cite**: confirm files/functions/routes exist (Glob/Grep/Read). Quote paths as `path/to/file.py:line`.
- **Verify library APIs against the installed version** (`node_modules/<pkg>/`, `site-packages`), and
  Sarvam APIs against https://docs.sarvam.ai — never from memory.
- **Unknown or ambiguous → write it down, do not guess**: add to *Open Questions* in `context/progress-tracker.md`.
- **Say what you did not verify.** "Built and lint passes" is not "works".
- **No fake functionality.** No fabricated test results, findings, devices or scores. If the harness is
  unreachable, runtime testing is reported as *skipped*, never simulated. Never claim a condition is
  simulated when `api/app/profiles.py` says it is not.
- **Do not expand scope.** Build what the active feature file says.

## 4. Working Rules

- Spec-driven: **no code for a feature until `features/fNN_*.md` exists and is filled in.**
- Protected paths (`web/components/ui/**`, `api/app/models.py`, `api/app/profiles.py`, `contracts/**`,
  `web/lib/types.ts`) are not edited unless the task says so.
- After each meaningful change: update `context/progress-tracker.md` and the feature file *Status Log*.
- Commit only when the user asks (or when the plan says a task ends in a commit).

## 5. Parallel Work (worktrees + sub-agents)

- Each parallel agent gets its **own git worktree and branch** and owns the disjoint files listed in
  its feature file (`Owned files`). Agents never edit files they do not own.
- Contracts are frozen before agents start. An agent needing a contract change stops and reports it.
- Every agent reports: files created/changed, commands run + real results, open questions.
- Orchestrator (Opus) reviews and merges; implementers are Sonnet. Nothing merges without tests/build passing.

## 6. Commands

| Purpose | Command |
| ------- | ------- |
| Install web | `cd web && npm install` |
| Install api | `cd api && uv sync` |
| Install harness (EC2) | `cd harness && uv sync` then `bash scripts/setup_ec2.sh` (once) |
| Dev web | `cd web && npm run dev` (http://localhost:3000) |
| Dev api | `cd api && uv run uvicorn app.main:app --reload --port 8000` |
| Dev harness (EC2) | `cd harness && uv run uvicorn harness.main:app --host 127.0.0.1 --port 8100` |
| Tunnel laptop→EC2 | `ssh -i secrets/<key>.pem -N -L 8100:127.0.0.1:8100 ubuntu@<EC2_IP>` |
| Lint / types web | `cd web && npm run lint && npx tsc --noEmit` |
| Test api / harness | `cd api && uv run pytest -q` · `cd harness && uv run pytest -q` |
| Build web | `cd web && npm run build` |

## 7. Repository Map

```text
api/            FastAPI: runs, pipeline, static analyzer, scoring, report, voice agent
  app/models.py     frozen contracts      app/profiles.py  frozen condition profiles
  app/analyzer/     static APK + runtime rules (f03)
  app/voice/        Sarvam voice agent (f05)
harness/        FastAPI service on EC2: emulator, ADB, profiles, crawler, evidence (f04)
web/            Next.js app: upload, live run, findings report, voice panel (f06, voice UI f05)
contracts/      frozen API / WS / harness / voice contracts
context/        project context (this template)
features/       one spec per feature
docs/superpowers/ design + plan
secrets/        (gitignored) EC2 .pem, IP, API keys
data/           (gitignored) uploaded APKs, run artifacts, sqlite db
```

## 8. Project Snapshot

- **Stack:** Next.js + TypeScript + Tailwind + shadcn/ui · FastAPI (Python 3.12+, uv) · SQLite now → Supabase later ·
  Sarvam STT/LLM/TTS · AWS EC2 + KVM + Android Emulator + ADB + Maestro · Resend (later)
- **Current phase:** see `context/progress-tracker.md`
- **Deferred:** GitHub repo → APK builds, Supabase Auth/DB/Storage, Resend emails, multi-device concurrency,
  physical-device conditions (thermal, slow CPU, OEM killers).

## 9. Do Not

- Do not commit `.env*`, `secrets/`, `data/` or `.pem` files. Never expose server keys to the browser.
- Do not give the voice agent shell access; it only calls the tools in `contracts/README.md` §6.
- Do not execute anything from an uploaded APK on the API host; APKs run only inside the emulator.
- Do not change the stack or add major dependencies without an *Architecture Decisions* entry first.
