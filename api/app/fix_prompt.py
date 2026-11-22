"""Fix-with-AI prompts (f26): deterministic Markdown prompts for an AI coding assistant.

Built only from real run data (Finding, AppInfo, Evidence, frozen profiles). No LLM call, nothing invented:
rule-specific guidance below is generic engineering advice and is labelled as such in the prompt.
"""

from __future__ import annotations

import re

from app.models import Finding, Run
from app.profiles import PROFILE_BY_ID

WEB_URL = "https://bharatbench-orpin.vercel.app"
FULL_LIMIT = 12_000
LOG_LINES = 40
EXCERPT_CHARS = 2_500
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# rule id -> (what to change, acceptance criteria)
_GUIDE: dict[str, tuple[str, list[str]]] = {
    "rt.crash": (
        ("Find the throwing frame in the stack trace, guard the null/invalid state or move the failing work to a safe "
        "place, and handle the failure path instead of letting it escape."),
        ["The app launches and the journey completes with no FATAL EXCEPTION in logcat under the same condition.",
         "A unit or instrumented test covers the failing input/state."],
    ),
    "rt.anr": (
        ("Find main-thread work: disk, database, network or heavy computation in onCreate/onResume/Application.onCreate "
        "or a click handler. Move it to a background dispatcher/executor and show a loading state."),
        ["No blocking I/O or network on the main thread (StrictMode.ThreadPolicy detectAll passes in debug).",
         "No ANR on the 2 GB budget profile (no 'ANR in' lines in logcat).",
         "Startup path does only the minimum work needed to draw the first screen."],
    ),
    "rt.launch_failed": (
        ("Find why the launcher activity does not start: an exception in Application/Activity init, a missing "
        "manifest entry, or an unsupported ABI/SDK."),
        ["The app's launcher activity opens to its first screen on the tested condition.",
         "No exception in Application.onCreate or the main activity's onCreate."],
    ),
    "rt.slow_launch": (
        ("Defer non-essential initialisation (SDKs, analytics, DI graphs, large reads) out of Application.onCreate and "
        "the first activity; lazy-init or use background threads / App Startup."),
        ["Cold start to first interactive screen is faster than the reported launch time under the same condition.",
         "No heavy synchronous work remains in Application.onCreate."],
    ),
    "rt.memory_high": (
        ("Reduce peak memory: downsample/cache bitmaps (Coil/Glide with size limits), avoid holding large lists or "
        "context references, release resources in onStop/onDestroy."),
        ["Peak PSS during the journey is lower than the reported figure on the 2 GB profile.",
         "No OutOfMemoryError or low-memory kill in logcat."],
    ),
    "rt.network_errors": (
        ("Add explicit connect/read timeouts, bounded retry with backoff for idempotent requests, and handle failures "
        "in the UI with an offline/error state and a Retry action."),
        ["Every network call has a timeout and a handled failure path (no unhandled exception on timeout/UnknownHost).",
         "Under the flaky/slow network profile the screen shows an offline or error state with Retry, not a blank screen.",
         "Idempotent requests retry with backoff; a successful retry recovers the screen without restarting the app."],
    ),
    "rt.stuck_loading": (
        ("Make sure every loading state ends: add timeouts, handle error and empty results, and always clear the "
        "progress indicator (finally block / terminal UI state)."),
        ["A loading indicator never stays for more than ~15 s; on failure an error state with Retry replaces it.",
         "Behaviour verified under the slow network profile."],
    ),
    "rt.state_lost": (
        ("Persist UI state that must survive process death: onSaveInstanceState / SavedStateHandle for transient "
        "state, a database or DataStore for user input and drafts; restore it in onCreate."),
        ["After the system kills the process and the app is restored from recents, the user sees the same screen and input.",
         "A test kills the process (adb shell am kill) and verifies restoration."],
    ),
    "rt.profile_not_applied": (
        ("This is a test-environment note rather than an app bug: the condition could not be applied by the harness. "
        "Do not change app code for it; re-run the test later."),
        ["Re-run the test; no app change is required for this item."],
    ),
    "rt.agent_test_failed": (
        ("Reproduce the failed custom test goal manually, find where the app diverges from the success check, and fix "
        "that screen/flow."),
        ["The custom test goal passes when re-run.", "The success check described in the finding is observable in the UI."],
    ),
    "sec.cleartext": (
        ("Replace every http:// endpoint with https://, remove android:usesCleartextTraffic=\"true\", and define a "
        "networkSecurityConfig that disallows cleartext (allow it only for a specific debug domain if truly needed)."),
        ["No http:// endpoints remain in code, config or remote-config defaults.",
         "A res/xml/network_security_config.xml with cleartextTrafficPermitted=\"false\" is referenced from the manifest.",
         "All API calls still work over HTTPS."],
    ),
    "sec.cleartext_traffic": (
        ("Set android:usesCleartextTraffic=\"false\" (or remove it) and add a networkSecurityConfig that forbids "
        "cleartext; move all endpoints to HTTPS."),
        ["Manifest no longer enables cleartext traffic; networkSecurityConfig forbids it.",
         "All API calls work over HTTPS."],
    ),
    "sec.http_urls": (
        ("Change hard-coded http:// URLs to https:// (confirm the server supports TLS); if a URL is only a namespace "
        "or documentation link it can stay, but say so in your summary."),
        ["No http:// network endpoints remain in code or resources.", "Affected features still work over HTTPS."],
    ),
    "sec.hardcoded_secret": (
        ("Remove the secret from the APK: rotate/revoke the exposed key now (assume it is compromised), then move the "
        "operation behind your own backend or use short-lived tokens. For keys that must ship (e.g. public Maps keys) "
        "restrict them by package name and SHA-1 in the provider console."),
        ["No secret, key or token literal remains in source, resources or BuildConfig.",
         "The exposed credential has been rotated or revoked (state this explicitly; never paste the real value anywhere).",
         "Secrets are read from a backend or secure runtime source, never committed to the repository."],
    ),
    "sec.debuggable": (
        ("Ensure android:debuggable is not true in the release build; debuggable is controlled by the build type "
        "(debuggable false for release)."),
        ["The release APK has no android:debuggable=\"true\" (verify the merged manifest)."],
    ),
    "sec.allow_backup": (
        ("Set android:allowBackup=\"false\" (or provide explicit dataExtractionRules/fullBackupContent excluding "
        "sensitive files such as tokens and databases)."),
        ["Manifest sets allowBackup=\"false\" or excludes sensitive data via backup rules."],
    ),
    "sec.exported_component": (
        ("For each flagged activity/service/receiver/provider: set android:exported=\"false\" unless it must be "
        "reachable by other apps; if it must be exported, protect it with a signature-level android:permission and "
        "validate all intent extras."),
        ["Each flagged component has exported=\"false\" or is protected by a permission.",
         "Components that stay exported validate untrusted intent data.",
         "The app's own flows still launch these components."],
    ),
    "sec.exported_components": (
        ("For each flagged component set android:exported=\"false\" unless another app must call it; otherwise "
        "require a signature-level permission and validate intent extras."),
        ["Each flagged component has exported=\"false\" or is protected by a permission.",
         "The app's own flows still work."],
    ),
    "sec.dangerous_permissions": (
        ("Remove permissions the app does not need; for the rest, request them at the moment of use with a clear "
        "rationale and handle denial gracefully."),
        ["Unused dangerous permissions are removed from the manifest.",
         "Remaining permissions are requested in context and denial does not crash or block the app."],
    ),
    "sec.webview_js_bridge": (
        ("Avoid addJavascriptInterface on WebViews that load remote or untrusted content; if needed, restrict to "
        "trusted HTTPS origins, annotate only required methods with @JavascriptInterface, and disable file access."),
        ["No JavaScript bridge is exposed to untrusted content.",
         "The WebView loads only trusted HTTPS origins; file access is disabled."],
    ),
    "sec.logcat_leaks": (
        ("Remove or strip log statements that print tokens, emails, phone numbers or request bodies (Timber with a "
        "release tree that logs nothing sensitive, or R8 -assumenosideeffects for Log.d/v)."),
        ["Sensitive values no longer appear in logcat during the journey.",
         "Release builds strip verbose/debug logging."],
    ),
    "sec.storage_secrets": (
        ("Do not store tokens or credentials in plain SharedPreferences/files; use EncryptedSharedPreferences or the "
        "Android Keystore, and store the minimum."),
        ["No secrets are stored in plain text on device storage.",
         "Existing plaintext values are migrated or cleared on upgrade."],
    ),
    "sec.storage_db": (
        ("Do not keep sensitive data unencrypted in app databases; encrypt (SQLCipher or field-level with Keystore "
        "keys) or avoid storing it."),
        ["Sensitive columns are encrypted or no longer stored.", "Database files are not world-readable."],
    ),
    "sec.world_readable": (
        "Create files and preferences with private mode only; share data through FileProvider with scoped URIs.",
        ["No file or preference is world-readable or world-writable.", "Sharing between apps goes through FileProvider."],
    ),
    "perf.no_shrinking": (
        ("Enable code and resource shrinking for release: minifyEnabled true (R8) and shrinkResources true in the "
        "release buildType, then add keep rules only where reflection or serialization requires them."),
        ["release buildType has minifyEnabled true and shrinkResources true.",
         "R8 keep rules exist for reflection/serialization classes and the release build runs the main flows without crashes.",
         "APK size is lower than the reported size."],
    ),
    "perf.apk_size": (
        ("Reduce APK size: enable R8 + shrinkResources, ship an Android App Bundle with ABI/density splits, convert "
        "images to WebP, remove unused libraries and assets."),
        ["APK size is lower than the reported size.", "App behaviour is unchanged (smoke test the main flows)."],
    ),
    "perf.multidex": (
        ("Reduce the number of dex files: remove unused dependencies, enable R8 shrinking and avoid pulling in whole "
        "SDKs for one function."),
        ["Dex count is lower after a release build.", "No functionality regression."],
    ),
    "perf.native_abis": (
        ("Ship only the ABIs you need (typically arm64-v8a, plus armeabi-v7a if you must support old devices) using "
        "ABI splits or bundle delivery; remove unused x86/x86_64 libs from release."),
        ["The release package contains only the intended ABIs.", "The app installs and runs on the target 2 GB phones."],
    ),
    "perf.old_target_sdk": (
        ("Raise targetSdk to the current Play requirement, then test and adapt to behaviour changes (permissions, "
        "background limits, exported flags, notifications)."),
        ["targetSdkVersion meets the current Play Store requirement.", "Main flows work on a current Android version."],
    ),
    "perf.min_sdk_high": (
        ("Consider lowering minSdk to reach more devices if the app's features allow it; use compat libraries and "
        "feature checks."),
        ["minSdk is lowered to the lowest version the app can reasonably support, or the reason it cannot be is recorded.",
         "The app still builds and passes tests."],
    ),
}

_FALLBACK = (
    "Use the description, evidence and suggested fix below to locate the cause, apply the smallest safe fix, and add a test.",
    ["The finding no longer appears when the test is re-run.", "A test covers the corrected behaviour.",
     "No unrelated behaviour changes."],
)

_VERIFY = (
    f"Rebuild the APK, upload it to {WEB_URL} (or re-run this test from the run page) and confirm the finding is "
    "gone in the Before/after card."
)
_CONSTRAINTS = [
    "Do not change unrelated code; keep existing behaviour.",
    "Make the smallest safe change and explain it.",
    "Never put secrets, keys or passwords in code, prompts or commit messages.",
    "If BharatBench's assessment looks wrong after reading the code, say so and explain instead of forcing a fix.",
]

_EXC = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:Exception|Error))\b")
_CLASS = re.compile(r"\b((?:[a-z][a-z0-9_]*\.){2,}[A-Za-z_][A-Za-z0-9_$]*)\b")
_URL = re.compile(r"https?://[^\s\"'<>)]+")
_SKIP_PREFIX = ("java.", "android.", "androidx.", "kotlin.", "com.android.", "dalvik.", "javax.")


def _guide(rule_id: str) -> tuple[str, list[str]]:
    return _GUIDE.get(rule_id, _FALLBACK)


def _trim(text: str, max_lines: int = LOG_LINES) -> str:
    lines = text.rstrip().splitlines()
    omitted = len(lines) - max_lines
    if omitted > 0:
        lines = [*lines[:max_lines], f"... ({omitted} more lines omitted)"]
    out = "\n".join(lines)
    return out if len(out) <= EXCERPT_CHARS else out[:EXCERPT_CHARS] + "\n... (truncated)"


def _fence(text: str, lang: str = "") -> list[str]:
    fence = "````" if "```" in text else "```"
    return [f"{fence}{lang}", text, fence]


def _search_terms(f: Finding, run: Run) -> list[str]:
    blob = "\n".join(e.excerpt or "" for e in f.evidence)
    terms: list[str] = []
    for rx in (_EXC, _CLASS, _URL):
        for m in rx.findall(blob):
            if m not in terms and not m.startswith(_SKIP_PREFIX):
                terms.append(m)
    if run.app and run.app.main_activity and run.app.main_activity not in terms:
        terms.append(run.app.main_activity)
    return terms[:8]


def _app_lines(run: Run, f: Finding | None = None) -> list[str]:
    a = run.app
    if a is None:
        return ["- App details were not available for this run."]
    out = [f"- Package: `{a.package_name}`" + (f" ({a.app_name})" if a.app_name else "")]
    if a.version_name or a.version_code:
        out.append(f"- Version: {a.version_name or 'unknown'} (code {a.version_code or 'unknown'})")
    out.append(
        f"- minSdk {a.min_sdk}, targetSdk {a.target_sdk}; APK size {a.size_bytes / 1_000_000:.1f} MB; "
        f"dex files {a.dex_count}"
    )
    out.append(f"- Native ABIs: {', '.join(a.native_abis) or 'none'}")
    if a.main_activity:
        out.append(f"- Main activity: `{a.main_activity}`")
    if f is not None and "permission" in f.rule_id and a.permissions:
        out.append(f"- Permissions declared ({len(a.permissions)}): " + ", ".join(f"`{p}`" for p in a.permissions[:25]))
    return out


def _cond_name(f: Finding) -> str:
    p = PROFILE_BY_ID.get(f.profile_id) if f.profile_id else None
    return p.name if p else "static analysis"


def _condition_lines(f: Finding) -> list[str]:
    if not f.profile_id:
        return ["- Condition: found by static analysis of the APK (no runtime condition)."]
    p = PROFILE_BY_ID.get(f.profile_id)
    if p is None:
        return [f"- Condition: `{f.profile_id}`"]
    return [f"- Condition: **{p.name}** ({p.fidelity}). How BharatBench applied it: {p.how}"]


def _text_evidence(f: Finding) -> list[tuple[str, str]]:
    labels = {"logcat": "Logcat", "manifest": "Manifest", "code": "Code", "metric": "Metric", "note": "Note"}
    return [(labels.get(e.kind, e.kind), e.excerpt) for e in f.evidence if e.excerpt and e.kind in labels]


def finding_prompt(run: Run, finding: Finding) -> str:
    f = finding
    fix_how, acceptance = _guide(f.rule_id)
    L: list[str] = [
        f"# Fix: {f.title}",
        "",
        ("You are fixing a reliability/security issue in an Android app, found by BharatBench on a real test phone. "
        "Work inside this app's repository."),
        "",
        "## App context",
        *_app_lines(run, f),
        "",
        "## The issue",
        f"- Title: {f.title}",
        f"- Severity: {f.severity} | Category: {f.category} | Rule: `{f.rule_id}` | Found by: {f.source} analysis",
        *_condition_lines(f),
    ]
    if f.affected_journey:
        L.append(f"- Journey: {f.affected_journey}" + (f" (step {f.journey_step})" if f.journey_step is not None else ""))
    if f.impact:
        L.append(f"- Estimated impact score: {f.impact.score} (assumption-based estimate, not measured telemetry)")
    L += ["", f.description, "", "## Evidence"]
    ev = _text_evidence(f)
    if ev:
        for label, text in ev:
            L += [f"{label}:", *_fence(_trim(text)), ""]
    else:
        L += ["No text evidence was captured for this finding (a screenshot may exist in the BharatBench report).", ""]
    if f.repro_steps:
        L += ["## Steps to reproduce", *[f"{n}. {s}" for n, s in enumerate(f.repro_steps, 1)], ""]
    if f.repro_flow:
        L += ["Maestro flow that reproduces it:", *_fence(f.repro_flow.rstrip(), "yaml"), ""]
    L += [
        "## BharatBench's assessment (verify in the code)",
        f"- Likely cause: {f.probable_cause or 'not determined by BharatBench'}",
        f"- Suggested fix: {f.suggested_fix or 'not provided by BharatBench'}",
        "",
    ]
    terms = _search_terms(f, run)
    find = "1. Find the relevant code" + (
        ". Search for: " + ", ".join(f"`{t}`" for t in terms)
        if terms
        else " using the evidence above (class, activity and manifest names)."
    )
    L += [
        "## What to do",
        find,
        f"2. {fix_how} (generic guidance for rule `{f.rule_id}`)",
        "3. Make the smallest safe fix and add or adjust a test that would have caught it.",
        "",
        "## Acceptance criteria",
        *[f"- {c}" for c in acceptance],
        "",
        "## How to verify",
        _VERIFY,
        "",
        "## Constraints",
        *[f"- {c}" for c in _CONSTRAINTS],
        "",
    ]
    return "\n".join(L)


def ranked(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-(f.impact.score if f.impact else 0.0), SEV_ORDER[f.severity]))


def _condensed(n: int, f: Finding, *, full: bool) -> list[str]:
    fix_how, acceptance = _guide(f.rule_id)
    head = f"### {n}. [{f.severity}] {f.title} (`{f.rule_id}`)"
    if not full:
        return [head, f"Condition: {_cond_name(f)}. Fix: {f.suggested_fix or fix_how}", ""]
    L = [head, f"Condition: {_cond_name(f)}. {f.description}"]
    ev = _text_evidence(f)
    if ev:
        L += [f"{ev[0][0]}:", *_fence(_trim(ev[0][1], 8))]
    L.append(f"Likely cause (BharatBench's assessment, verify): {f.probable_cause or 'not determined'}")
    L.append(f"Fix: {f.suggested_fix or fix_how}")
    L.append("Done when: " + "; ".join(acceptance[:3]))
    L.append("")
    return L


def report_prompt(run: Run, findings: list[Finding], limit: int = FULL_LIMIT) -> str:
    items = ranked(findings)
    name = run.app.package_name if run.app else run.apk_name
    head: list[str] = [
        f"# Fix all issues found by BharatBench in {name}",
        "",
        ("You are fixing reliability and security issues in an Android app, found by BharatBench on a real test phone. "
        "Work inside this app's repository."),
        "",
        "## App context",
        *_app_lines(run),
        "",
        "## Issues in priority order (highest impact first)",
        "",
        "| # | Severity | Issue | Rule | Condition |",
        "| - | -------- | ----- | ---- | --------- |",
    ]
    for n, f in enumerate(items, 1):
        head.append(f"| {n} | {f.severity} | {f.title.replace('|', '/')} | `{f.rule_id}` | {_cond_name(f)} |")
    head.append("")
    tail = [
        "## Verification checklist",
        f"- [ ] {_VERIFY}",
        "- [ ] Every issue above is gone, or has a written reason it was left.",
        "- [ ] Existing tests pass and each fix has a test.",
        "",
        "## How to work",
        ("Work issue by issue in the order above, one commit per issue (the message names the rule id). "
        "Verify each against its done-when criteria before moving on."),
        *[f"- {c}" for c in _CONSTRAINTS],
        "",
    ]
    if not items:
        return "\n".join([*head, "No issues were found; nothing to fix.", "", *tail])

    budget = limit - len("\n".join(head)) - len("\n".join(tail)) - 250

    def size(secs: list[list[str]]) -> int:
        return sum(len("\n".join(s)) + 1 for s in secs)

    sections = [_condensed(n, f, full=True) for n, f in enumerate(items, 1)]
    shortened = 0
    for idx in range(len(items) - 1, -1, -1):  # degrade lowest priority first
        if size(sections) <= budget:
            break
        sections[idx] = _condensed(idx + 1, items[idx], full=False)
        shortened += 1
    omitted = 0
    while len(sections) > 1 and size(sections) > budget:
        sections.pop()
        omitted += 1
    body = ["## Issues in detail", ""]
    for s in sections:
        body += s
    if shortened or omitted:
        note = f"Note: to keep this prompt short, {shortened} lower-priority issue(s) are condensed"
        if omitted:
            note += f" and {omitted} more appear only in the table above (open each finding in BharatBench for its own prompt)"
        body += [note + ".", ""]
    out = "\n".join([*head, *body, *tail])
    return out if len(out) <= limit else out[: limit - 40] + "\n... (truncated)\n"
