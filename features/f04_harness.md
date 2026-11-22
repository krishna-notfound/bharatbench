# f04 — Harness service (EC2): emulator, profiles, crawler, evidence

**Status:** Built (merged to main; see docs/FEATURE_MAP.md)  |  **Depends on:** f01  |  **Owner:** Sonnet agent `harness`

## Purpose

A standalone FastAPI service on an Ubuntu EC2 host with KVM that installs an APK on a running Android
emulator, applies each condition profile, runs an automated journey, and returns real evidence
(`HarnessResult`). It is the only component that touches ADB.

## Scope

**In:** `harness/` project, EC2 setup + emulator scripts, API in `contracts/README.md` §4, profile
appliers (apply + guaranteed revert), crawler, evidence collection, parsers, tests with subprocess mocked.
**Out:** scoring/findings (api f03 turns results into findings), building APKs, multiple devices.

## Routes / Files

**Owned files:** everything under `harness/`:
- `harness/pyproject.toml` (uv; deps: fastapi, uvicorn[standard], pydantic, pydantic-settings, python-multipart; dev: pytest, pytest-asyncio, ruff)
- `harness/harness/models.py` — **copy** of the harness section of `api/app/models.py` (HarnessJobRequest … HarnessResult, ProfileId literal) — must stay byte-compatible in JSON
- `harness/harness/main.py`, `settings.py` (HARNESS_TOKEN required, ANDROID_SERIAL=emulator-5554, JOBS_DIR=./jobs, ADB_PATH=adb, MAESTRO_PATH=maestro)
- `harness/harness/adb.py` — async wrapper: `run(args, timeout) -> (rc, out, err)` using `asyncio.create_subprocess_exec`, never shell
- `harness/harness/profiles.py` — `async apply(profile_id) -> str(note)` / `async revert(profile_id)` per profile
- `harness/harness/crawler.py`, `evidence.py`, `parsers.py`, `jobs.py` (single-job runner + state)
- `harness/scripts/setup_ec2.sh`, `harness/scripts/start_emulator.sh`, `harness/scripts/harness.service` (systemd unit), `harness/README.md`, `harness/.env.example`
- `harness/tests/**` (fixtures: sample logcat with FATAL EXCEPTION/ANR/SocketTimeoutException, sample uiautomator XML)

**Read-only:** `api/app/models.py`, `api/app/profiles.py` (the `how` text is the spec for each profile), `contracts/README.md`.

## Mechanisms (implement exactly; verify each adb command in Android docs if unsure)

- Setup (`setup_ec2.sh`, Ubuntu 24.04): fail fast if `/dev/kvm` missing (print instance-type advice); apt openjdk-17-jdk-headless, unzip, curl; Android cmdline-tools → `sdkmanager "platform-tools" "emulator" "system-images;android-34;google_apis;x86_64"`; `avdmanager create avd -n bb_budget -k <image> -d pixel_4`; set in `config.ini`: `hw.ramSize=2048`, `disk.dataPartition.size=6G`, `hw.keyboard=yes`; install Maestro (`curl -Ls "https://get.maestro.mobile.dev" | bash`); add user to `kvm` group; uv install.
- `start_emulator.sh`: `emulator -avd bb_budget -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -no-snapshot-save &`, wait `adb wait-for-device` + `getprop sys.boot_completed`==1 (timeout 300 s), then `settings put global window_animation_scale 0` (+ transition/animator).
- Install: `adb install -r -g app.apk` (timeout 180 s). Uninstall after the job.
- Before each profile: `am force-stop <pkg>`, `pm clear <pkg>`, `logcat -c`.
- `baseline`: nothing (note "no shaping").
- `budget_2gb`: `adb emu network speed 2000:2000`, `adb emu network delay 200:600`; revert `network speed full`, `network delay none`. Note RAM is fixed by AVD (2048 MB).
- `flaky_network`: background task during journey toggling `svc data disable; svc wifi disable` (6 s) then enable (4 s); revert = enable both.
- `low_storage`: read `df /data` free KB, `fallocate -l <free-400MB> /data/local/tmp/bb_filler` (fallback `dd`); revert `rm -f`. If free < 400 MB already, note it.
- `battery_saver`: `dumpsys battery unplug`, `dumpsys battery set level 10`, `settings put global low_power 1`; revert `settings put global low_power 0`, `dumpsys battery reset`.
- `process_death`: after crawl step 2: dump UI (before), `input keyevent KEYCODE_HOME`, `am kill <pkg>`, relaunch via `monkey -p <pkg> -c android.intent.category.LAUNCHER 1`, wait 4 s, dump UI (after); `state_lost_after_restore = True` if the set of visible text nodes overlaps < 50% and after-activity == launcher activity.
- All reverts in `try/finally`; revert failures recorded in job events, never raised.
- Launch: `am start -W -n <pkg>/<activity>` (activity from request or `cmd package resolve-activity --brief`); parse `TotalTime` → `launch_ms`; `launched=False` if no window or crash within 5 s.
- Crawler (`journey_steps`, default 8): per step `uiautomator dump /sdcard/ui.xml` + `exec-out cat` → parse clickable nodes (bounds, text, content-desc, resource-id); skip already tapped and denylist labels (logout, log out, sign out, delete, remove, pay, buy, purchase, checkout, uninstall, call, sms); pick first unvisited (prefer text); `input tap cx cy`; wait for idle up to 3 s; screenshot (`exec-out screencap -p` → `screens/{profile}_{i}.png`), save UI xml; if app left foreground (`dumpsys activity activities | grep mResumedActivity`), press back once / relaunch. If nothing clickable: `input keyevent KEYCODE_BACK`.
- Stuck loading: same screen (UI xml hash) containing a `ProgressBar` class for ≥ 15 s of consecutive checks → `stuck_loading=True`.
- Evidence: after profile `logcat -d -v threadtime` → `logcat/{profile}.txt`; parse crashes (`FATAL EXCEPTION`, `ANR in <pkg>`, `Fatal signal` for native), network errors (`SocketTimeoutException`, `UnknownHostException`, `ConnectException`, `SSLHandshakeException`, `java.io.IOException: unexpected end of stream`) — lines filtered to the app's PID or package where possible; `dumpsys meminfo <pkg>` TOTAL PSS → `memory_pss_kb`.
- Maestro flow: generated by api analyzer from steps; harness additionally writes `flows/{profile}.yaml` itself only if trivial — not required.
- Job runner: one job at a time (asyncio.Lock); 409 if busy; job dir `JOBS_DIR/{job_id}`; overall timeout 12 min; cancel sets a flag checked between steps; progress = done_profiles/len.

## Rules and Edge Cases

1. Token check on every route (constant-time compare). Bind 127.0.0.1 in systemd unit.
2. Artifact route rejects traversal; serves only files inside the job dir.
3. Emulator not booted → `/health` `emulator_booted:false`; POST /jobs → 503 with clear message.
4. Every adb call has a timeout; a hung command fails that step, not the job.

## Tasks

- [ ] uv project, models copy, settings, token auth, health (tests)
- [ ] parsers TDD (logcat crash/ANR/network, uiautomator XML → clickable nodes, `am start -W` output, meminfo, df)
- [ ] adb wrapper + profiles apply/revert (tests assert exact adb arg lists with mocked runner)
- [ ] crawler + evidence + job runner (mocked adb)
- [ ] setup/start scripts + systemd unit + README (EC2 steps, SSH tunnel command)

## Acceptance Criteria

- [ ] `cd harness && uv run pytest -q` passes on Windows/Linux without an emulator.
- [ ] On EC2 after setup: `/health` shows the booted emulator; a job with a real APK returns screenshots + logcat.

## Verification

`cd harness && uv sync && uv run pytest -q && uv run ruff check .`

## Status Log

- 2026-11-21 — Specced.
- 2026-11-21 — Implemented on branch feat/f04-harness: harness service, parsers, profiles, crawler, evidence, job runner, scripts, systemd unit, README. 38 tests (mocked adb) + ruff pass; local uvicorn /health observed 401 without token / 200 with. Not verified: anything needing a real emulator/EC2 (see harness/README.md "Verified vs assumed").
