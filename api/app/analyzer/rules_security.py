"""Static security rules: pure functions (ApkFacts, run_id) -> list[Finding]."""

import re

from app.analyzer.apk import ApkFacts
from app.analyzer.ids import finding_id
from app.models import Evidence, Finding, Severity

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    "Stripe live key": re.compile(r"sk_live_[0-9a-zA-Z]{24,}"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    "Slack token": re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
}

DANGEROUS_PERMISSIONS = [
    "READ_SMS",
    "SEND_SMS",
    "READ_CALL_LOG",
    "READ_CONTACTS",
    "ACCESS_FINE_LOCATION",
    "RECORD_AUDIO",
    "CAMERA",
    "READ_EXTERNAL_STORAGE",
    "MANAGE_EXTERNAL_STORAGE",
    "SYSTEM_ALERT_WINDOW",
    "REQUEST_INSTALL_PACKAGES",
]

_HTTP_URL = re.compile(r"http://[^\s\"'<>]+")
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "10.0.2.2", "0.0.0.0", "[::1]")
_SCHEMA_HOSTS = (
    "schemas.android.com",
    "w3.org",
    "xmlpull.org",
    "schemas.microsoft.com",
    "ns.adobe.com",
    "xml.org",
    "java.sun.com",
    "apache.org",
    "purl.org",
    "logback.qos.ch",
    "slf4j.org",
    "iana.org",
    "ietf.org",
    "opengis.net",
    "xmlns.com",
)


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() == "true"


def mask(secret: str) -> str:
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}****{secret[-4:]}"


def _finding(
    run_id: str,
    rule_id: str,
    n: int,
    title: str,
    severity: Severity,
    description: str,
    evidence: list[Evidence],
    cause: str,
    fix: str,
) -> Finding:
    return Finding(
        id=finding_id(run_id, rule_id, n),
        run_id=run_id,
        source="static",
        category="security",
        rule_id=rule_id,
        title=title,
        severity=severity,
        description=description,
        evidence=evidence,
        profile_id=None,
        journey_step=None,
        probable_cause=cause,
        suggested_fix=fix,
    )


def check_debuggable(facts: ApkFacts, run_id: str) -> list[Finding]:
    if not _truthy(facts.app_attrs.get("debuggable")):
        return []
    return [
        _finding(
            run_id,
            "sec.debuggable",
            1,
            "App is debuggable",
            "critical",
            "android:debuggable=true lets anyone attach a debugger, read app data and run code in the app.",
            [Evidence(kind="manifest", excerpt='<application android:debuggable="true">')],
            "Debug build or manifest override shipped as release.",
            "Build a release variant; remove android:debuggable from the manifest.",
        )
    ]


def check_cleartext(facts: ApkFacts, run_id: str) -> list[Finding]:
    declared = _truthy(facts.app_attrs.get("usesCleartextTraffic"))
    legacy = (
        facts.target_sdk is not None
        and facts.target_sdk < 28
        and facts.network_security_config is None
    )
    if not (declared or legacy):
        return []
    if declared:
        excerpt = 'android:usesCleartextTraffic="true"'
    else:
        excerpt = f"targetSdkVersion={facts.target_sdk} (<28), no network security config"
    return [
        _finding(
            run_id,
            "sec.cleartext",
            1,
            "Cleartext HTTP traffic allowed",
            "high",
            "The app may send data over unencrypted HTTP, exposing it on public or shared networks.",
            [Evidence(kind="manifest", excerpt=excerpt)],
            "Cleartext traffic is enabled explicitly or by an old target SDK default.",
            "Use HTTPS everywhere, set usesCleartextTraffic=false and add a network security config.",
        )
    ]


def check_hardcoded_secrets(facts: ApkFacts, run_id: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for s in facts.strings:
        for label, pattern in SECRET_PATTERNS.items():
            for m in pattern.finditer(s):
                value = m.group(0)
                if value in seen:
                    continue
                seen.add(value)
                findings.append(
                    _finding(
                        run_id,
                        "sec.hardcoded_secret",
                        len(findings) + 1,
                        f"Hardcoded secret: {label}",
                        "critical",
                        f"A {label} is embedded in the APK and can be extracted by anyone.",
                        [Evidence(kind="code", excerpt=mask(value))],
                        "Credential stored in source or resources.",
                        "Revoke and rotate the key; move it to a backend and fetch short-lived tokens.",
                    )
                )
    return findings


def check_exported_components(facts: ApkFacts, run_id: str) -> list[Finding]:
    findings: list[Finding] = []
    for c in facts.components:
        if c.exported is not True or c.permission:
            continue
        if c.kind == "activity" and (c.name == facts.main_activity or c.launcher or c.deep_link):
            continue  # launcher and deep-link activities must be exported
        severity: Severity = "high" if c.kind == "provider" else "medium"
        if c.kind == "activity" and c.has_intent_filter:
            severity = "low"  # activities with intent filters are routinely exported by design
        findings.append(
            _finding(
                run_id,
                "sec.exported_component",
                len(findings) + 1,
                f"Exported {c.kind} without permission: {c.name}",
                severity,
                f"The {c.kind} {c.name} is reachable by any app on the device.",
                [
                    Evidence(
                        kind="manifest",
                        excerpt=f'<{c.kind} android:name="{c.name}" android:exported="true">',
                    )
                ],
                "Component exported without a guarding permission.",
                "Set android:exported=false or require a signature-level permission.",
            )
        )
    return findings


def check_allow_backup(facts: ApkFacts, run_id: str) -> list[Finding]:
    value = facts.app_attrs.get("allowBackup")
    unset_legacy = value is None and facts.target_sdk is not None and facts.target_sdk < 31
    if not (_truthy(value) or unset_legacy):
        return []
    if value is not None:
        excerpt = 'android:allowBackup="true"'
    else:
        excerpt = "allowBackup unset (defaults to true below targetSdk 31)"
    return [
        _finding(
            run_id,
            "sec.allow_backup",
            1,
            "App data can be backed up via adb",
            "medium",
            "Backups let app data be extracted from the device.",
            [Evidence(kind="manifest", excerpt=excerpt)],
            "allowBackup is enabled explicitly or by default.",
            'Set android:allowBackup="false" or define backup rules excluding sensitive data.',
        )
    ]


def check_dangerous_permissions(facts: ApkFacts, run_id: str) -> list[Finding]:
    held = sorted({p.rsplit(".", 1)[-1] for p in facts.permissions} & set(DANGEROUS_PERMISSIONS))
    if not held:
        return []
    severity: Severity = "high" if len(held) >= 4 else "medium"
    return [
        _finding(
            run_id,
            "sec.dangerous_permissions",
            1,
            f"{len(held)} sensitive permission(s) requested",
            severity,
            "Sensitive permissions raise privacy risk and install friction: " + ", ".join(held) + ".",
            [Evidence(kind="manifest", excerpt=", ".join(held))],
            "App requests broad permissions.",
            "Remove permissions not essential to core flows; request the rest at the point of use.",
        )
    ]


def check_http_urls(facts: ApkFacts, run_id: str) -> list[Finding]:
    urls: list[str] = []
    for s in facts.strings:
        for m in _HTTP_URL.finditer(s):
            url = m.group(0)
            host = url[len("http://") :].split("/")[0].split(":")[0].lower()
            if not host or "." not in host or host in _LOCAL_HOSTS or any(host == h or host.endswith("." + h) for h in _SCHEMA_HOSTS):
                continue
            if url not in urls:
                urls.append(url)
    if not urls:
        return []
    return [
        _finding(
            run_id,
            "sec.http_urls",
            1,
            f"{len(urls)} plain http:// URL(s) in code",
            "low",
            "Hardcoded non-HTTPS URLs found in the app.",
            [Evidence(kind="code", excerpt=u) for u in urls[:10]],
            "Endpoints referenced over HTTP.",
            "Switch to https:// endpoints.",
        )
    ]


def check_webview_js_bridge(facts: ApkFacts, run_id: str) -> list[Finding]:
    if not facts.uses_webview_js:
        return []
    return [
        _finding(
            run_id,
            "sec.webview_js_bridge",
            1,
            "WebView JavaScript bridge in use",
            "medium",
            "addJavascriptInterface exposes native objects to web content; untrusted pages can call them.",
            [Evidence(kind="code", excerpt="addJavascriptInterface referenced")],
            "Native object exposed to JavaScript.",
            "Only load trusted https content, annotate with @JavascriptInterface, minimise exposed methods.",
        )
    ]


RULES = [
    check_debuggable,
    check_cleartext,
    check_hardcoded_secrets,
    check_exported_components,
    check_allow_backup,
    check_dangerous_permissions,
    check_http_urls,
    check_webview_js_bridge,
]


def security_findings(facts: ApkFacts, run_id: str) -> list[Finding]:
    return [f for rule in RULES for f in rule(facts, run_id)]
