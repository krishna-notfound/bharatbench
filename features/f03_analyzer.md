# f03 — Analyzer: static APK scan + runtime evidence rules

**Status:** Done  |  **Depends on:** f01  |  **Owner:** Sonnet agent `analyzer`

## Purpose

Turn an APK and a `HarnessResult` into evidence-backed `Finding`s: security + performance from the APK
itself, reliability/network/storage/memory from runtime evidence.

## Scope

**In:** `analyze_apk`, `runtime_findings`, all rules below, tests.
**Out:** scoring (f02 sets `impact`), I/O beyond reading the APK, network calls.

## Routes / Files

**Owned files:**
- `api/app/analyzer/__init__.py` (exports the two functions), `api/app/analyzer/apk.py` (androguard loading → `ApkFacts`),
  `api/app/analyzer/rules_security.py`, `api/app/analyzer/rules_performance.py`, `api/app/analyzer/rules_runtime.py`,
  `api/app/analyzer/maestro.py` (steps → Maestro YAML), `api/app/analyzer/ids.py`
- `api/tests/analyzer/**` (fixtures + tests)

**Read-only:** `api/app/models.py`, `api/app/profiles.py`. Do not touch `api/pyproject.toml` (f02 adds `androguard`); if you need another dep, report it.

## Data and Interfaces

```python
def analyze_apk(apk_path: Path, run_id: str) -> tuple[AppInfo, list[Finding]]   # sync; caller uses to_thread
def runtime_findings(run_id: str, result: HarnessResult) -> list[Finding]
def steps_to_maestro(package: str, steps: list[HarnessStep], screens: list[HarnessScreen]) -> str
```
- `apk.py`: `@dataclass ApkFacts(manifest_xml: str, package, app_name, version_name, version_code, min_sdk, target_sdk, size_bytes, permissions, main_activity, components: list[Component(kind, name, exported: bool|None, permission, has_intent_filter)], app_attrs: dict, network_security_config: str|None, strings: list[str], native_abis, dex_count, class_names_sample: list[str], uses_webview_js: bool)`.
  Rules are pure functions `(facts: ApkFacts, run_id) -> list[Finding]` so they are testable without an APK.
- Finding ids: `f"{run_id[:8]}-{rule_id}-{n}"`. All static findings: `source="static"`, `profile_id=None`, `journey_step=None`.

## Rules (rule_id → severity)

Security (`category="security"`):
- `sec.debuggable` → critical (`android:debuggable=true`)
- `sec.cleartext` → high (`usesCleartextTraffic=true`, or targetSdk < 28 without network security config)
- `sec.hardcoded_secret` → critical per distinct match; regexes: AWS `AKIA[0-9A-Z]{16}`, Google `AIza[0-9A-Za-z\-_]{35}`, Stripe `sk_live_[0-9a-zA-Z]{24,}`, private key `-----BEGIN (RSA |EC )?PRIVATE KEY-----`, Slack `xox[baprs]-[0-9A-Za-z-]{10,}`, GitHub `gh[pousr]_[A-Za-z0-9]{36}`. Evidence excerpt masks middle chars (`AKIA****XYZ1`).
- `sec.exported_component` → high for exported activity/service/receiver/provider with no `permission` (skip the launcher activity); provider → high, others medium.
- `sec.allow_backup` → medium (`allowBackup` true or unset with targetSdk < 31)
- `sec.dangerous_permissions` → medium if any of READ_SMS, SEND_SMS, READ_CALL_LOG, READ_CONTACTS, ACCESS_FINE_LOCATION, RECORD_AUDIO, CAMERA, READ_EXTERNAL_STORAGE, MANAGE_EXTERNAL_STORAGE, SYSTEM_ALERT_WINDOW, REQUEST_INSTALL_PACKAGES (list them; ≥ 4 → high)
- `sec.http_urls` → low (non-localhost `http://` URLs in strings; max 10 in evidence)
- `sec.webview_js_bridge` → medium (`addJavascriptInterface` referenced)

Performance (`category="performance"`):
- `perf.apk_size` → >100 MB high, >50 MB medium, >25 MB low (Indian users on limited data/storage)
- `perf.native_abis` → medium if > 2 ABIs bundled in one APK (suggest App Bundle splits)
- `perf.multidex` → low if dex_count > 3
- `perf.no_shrinking` → medium if < 5% of sampled app class names look obfuscated (1–2 char segments)
- `perf.old_target_sdk` → targetSdk < 33 medium; `perf.min_sdk_high` → low if minSdk > 28 (excludes older budget phones)

Runtime (`source="runtime"`, `profile_id` set, evidence must reference artifacts):
- `rt.crash` → critical (category reliability) per crash; evidence logcat excerpt + last screenshot; journey_step = step at crash.
- `rt.anr` → critical (reliability).
- `rt.launch_failed` → critical if `launched=false`.
- `rt.slow_launch` → `launch_ms` > 5000 high, > 2000 medium (performance); compare to baseline if present in description.
- `rt.network_errors` → high (network) if `network_errors` non-empty (dedupe exception types).
- `rt.stuck_loading` → high (network).
- `rt.state_lost` → high (reliability) when `state_lost_after_restore` is True.
- `rt.memory_high` → medium (memory) if `memory_pss_kb` > 300_000 on budget_2gb.
- `rt.profile_not_applied` → low note when `applied=false` (category matches profile), so users see what did not run.
Each runtime finding: `repro_steps` (human list: apply profile `how`, launch, steps up to failure), `repro_flow` from `steps_to_maestro`, `affected_journey="Auto crawl"`, `probable_cause` and `suggested_fix` from a per-rule template (e.g. network: "Requests without timeout/retry; add OkHttp timeouts + retry with backoff + offline state").

## Rules and Edge Cases

1. Broken/non-APK file → raise `ValueError("Not a valid APK: ...")` (f02 marks run failed).
2. Strings scan capped at 200k strings; skip strings > 2 KB.
3. Never emit a runtime finding without at least one `Evidence`.
4. Maestro YAML: `appId: <pkg>` header, `---`, `- launchApp`, `- tapOn: "<text>"` when target is text, `- tapOn: {id: "<res-id>"}` for ids, `- tapOn: {point: "x,y"}` otherwise, `- back`, `- pressKey: Home`, `- stopApp`, `- assertVisible` not used.

## Tasks

- [ ] apk.py facts extraction (verify androguard API in installed package: `androguard.core.apk.APK` / `androguard.misc.AnalyzeAPK` — check version)
- [ ] security rules TDD with synthetic ApkFacts
- [ ] performance rules TDD
- [ ] runtime rules + maestro TDD with synthetic HarnessResult
- [ ] smoke test on a real APK if available (download not required; skip test if no fixture)

## Acceptance Criteria

- [ ] `uv run pytest -q api/tests/analyzer` passes; each rule has a positive and a negative test.
- [ ] `analyze_apk` on a real APK returns AppInfo + findings without exceptions.

## Verification

`cd api && uv sync && uv run pytest -q tests/analyzer` (deps incl. androguard are already in `api/pyproject.toml`).

## Status Log

- 2026-11-21 — Specced.
- 2026-11-21 — Implemented: analyzer package, all rules, maestro, tests (48 pass incl. real F-Droid APK smoke via BB_SAMPLE_APK). `runtime_findings` takes optional `package` (3rd arg) for Maestro appId. ApkFacts/Component live in apk.py.
