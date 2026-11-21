# BharatBench

## Overview

BharatBench is a web platform that tests Android apps where Indian users actually are: everyday 2 GB
phones, slow and dropping mobile networks, nearly full storage, battery saver, and apps killed in the
background. A developer uploads an APK; BharatBench scans it for security and performance problems,
runs it on a real Android emulator under constrained profiles, collects evidence (screenshots, UI
dumps, logcat, timings), ranks every finding by estimated user impact, and produces reproducible
Maestro flows. A voice agent (Hindi / English / Hinglish) can start tests, report progress and explain
findings. Tagline: **"The Real Phone Test — test your app where your users actually are."** Copy rule (2026-11-21, user): never use the word "cheap" in product copy — say "everyday phones" / "the phones your users really carry"; "Budget Android" is fine as a profile name.

## Goals

1. Find real failures under Indian-device conditions with real execution evidence — never fabricated.
2. Rank findings by user impact (users exposed × severity × flow usage) with transparent, adjustable assumptions.
3. Give developers actionable output: cause, fix, evidence, and a Maestro repro flow per finding.
4. Let users drive and understand testing by voice in their language.

## Users and Roles

| Role | Who | Can do | Must never |
| ---- | --- | ------ | ---------- |
| Developer | App developer / QA uploading an APK | Upload APK, pick profiles, watch run, read report, talk to agent | See other users' runs (once auth exists) |
| Voice agent | LLM orchestrator in `api/app/voice` | Call tools in `contracts/README.md` §6 | Run shell commands, touch the harness directly, invent results |
| Operator | Team member running the EC2 harness | Start emulator, tunnel, restart harness | Expose harness port publicly |

(No auth in the prototype; Supabase Auth is deferred.)

## Core User Flows

### Test an app
1. Developer opens `/`, drops an `.apk`, picks condition profiles (fidelity badge shown on each).
2. API stores the APK, creates a run, returns run id; UI navigates to `/runs/{id}`.
3. Live timeline streams: static scan → harness provisioning → each profile (launch, crawl steps, conditions) → scoring.
4. Report shows reliability score, findings ranked by impact, evidence, fix and Maestro repro; markdown export.

### Ask by voice
1. Developer taps the mic (any page), speaks e.g. "mera app slow network pe test karo".
2. Agent calls `start_test` (re-run of the current APK) and says what it is doing.
3. While the run progresses the agent speaks short updates; afterwards "sabse bada issue kya hai?" → `list_findings` + `explain_finding`.
4. Developer can interrupt the agent mid-sentence; playback stops instantly.

## Features

### Static APK analysis (f03)
- Security: debuggable, allowBackup, cleartext traffic, exported components without permission, dangerous permissions, hardcoded secrets/keys, http URLs, WebView JS bridges.
- Performance/size: APK size, dex count, native ABIs bundled, min/target SDK, missing shrinking/obfuscation.

### Real-phone runtime testing (f04)
- Profiles in `api/app/profiles.py`; launch timing, automated crawl journey, crash/ANR detection, network error detection, stuck-loading detection, state loss after process death, memory PSS.

### Impact ranking and repro (f02)
- Score per finding, overall reliability score, markdown report, Maestro YAML per runtime finding.

### Voice agent (f05)
- Sarvam streaming STT → Sarvam LLM with tools → Sarvam TTS, barge-in, run progress narration.

### Web app (f06)
- Upload, runs list, live run view, findings report with evidence viewer, voice panel.

## Scope

### In Scope
- APK upload input only; one harness host, one emulator, one job at a time.
- Static + runtime analysis, scoring, report, voice agent, web UI.

### Out Of Scope
- iOS, physical device farm, Play Store integration, payments.

### Deferred (decided, not now)
- GitHub repo → Gradle build → APK — untrusted build scripts + toolchain variance; revisit after demo.
- Supabase DB/Auth/Storage — teammate connects later; storage sits behind `api/app/storage` interface.
- Resend emails (run finished) — after Supabase Auth gives user emails.
- Parallel emulators / job queue — one job at a time is enough for demo.

## Business Rules

1. A runtime finding must cite at least one evidence item from an actual harness run.
2. A profile whose `fidelity` is `unsupported` is never offered as runnable; approximations are labelled.
3. If the harness is unavailable the run completes with static findings and `runtime_skipped_reason`; nothing runtime is faked.
4. Impact score = 100 × users_exposed × severity_weight × flow_usage, each factor shown with the finding.
5. APK > 200 MB or non-APK upload is rejected (413/400).
6. Voice agent cancels a run only on explicit user request.

## Success Criteria

1. Uploading a real APK produces static findings with evidence within 60 s.
2. With the EC2 harness tunnelled, a run executes ≥ 2 profiles on the emulator and returns screenshots + logcat.
3. A crashing/stalling test app yields a ranked runtime finding with a Maestro repro flow.
4. Voice: asking in Hinglish starts a test and gets a spoken answer; barge-in stops speech within ~300 ms.

## Glossary

| Term | Meaning |
| ---- | ------- |
| Run | One test of one APK across selected profiles |
| Profile | A constrained device condition set (`api/app/profiles.py`) |
| Fidelity | controlled / approximated / unsupported — how real the simulation is |
| Harness | The EC2 service that drives the emulator via ADB/Maestro |
| Journey | Automated crawl of the app's UI (launch + N taps) |
| Finding | A ranked problem with evidence, cause, fix, repro |
| Impact score | 0–100, users_exposed × severity × flow usage |
