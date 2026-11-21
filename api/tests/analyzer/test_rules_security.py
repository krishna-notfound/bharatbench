from app.analyzer.apk import Component
from app.analyzer.rules_security import (
    check_allow_backup,
    check_cleartext,
    check_dangerous_permissions,
    check_debuggable,
    check_exported_components,
    check_hardcoded_secrets,
    check_http_urls,
    check_webview_js_bridge,
    mask,
    security_findings,
)

AWS = "AKIAABCDEFGHIJKLMNOP"
GOOGLE = "AIza" + "a" * 35
STRIPE = "sk_live_" + "b" * 24
SLACK = "xoxb-1234567890-abcdef"
GITHUB = "ghp_" + "c" * 36


def test_clean_facts_have_no_findings(make_facts, run_id):
    assert security_findings(make_facts(), run_id) == []


def test_debuggable_positive(make_facts, run_id):
    (f,) = check_debuggable(make_facts(app_attrs={"debuggable": "true"}), run_id)
    assert f.rule_id == "sec.debuggable" and f.severity == "critical" and f.source == "static"
    assert f.category == "security" and f.profile_id is None and f.journey_step is None
    assert f.id == "abcdef12-sec.debuggable-1"
    assert f.evidence[0].kind == "manifest"


def test_debuggable_negative(make_facts, run_id):
    assert check_debuggable(make_facts(app_attrs={"debuggable": "false"}), run_id) == []
    assert check_debuggable(make_facts(), run_id) == []


def test_cleartext_explicit_positive(make_facts, run_id):
    (f,) = check_cleartext(make_facts(app_attrs={"usesCleartextTraffic": "true"}), run_id)
    assert f.severity == "high" and f.rule_id == "sec.cleartext"


def test_cleartext_old_target_without_nsc_positive(make_facts, run_id):
    (f,) = check_cleartext(make_facts(target_sdk=27), run_id)
    assert "27" in f.evidence[0].excerpt


def test_cleartext_negative(make_facts, run_id):
    assert check_cleartext(make_facts(target_sdk=27, network_security_config="@xml/nsc"), run_id) == []
    assert check_cleartext(make_facts(), run_id) == []


def test_secrets_positive_all_patterns_masked(make_facts, run_id):
    private_key = "-----BEGIN RSA PRIVATE KEY-----"
    strings = [f"k={AWS}", GOOGLE, STRIPE, private_key, SLACK, GITHUB]
    findings = check_hardcoded_secrets(make_facts(strings=strings), run_id)
    assert len(findings) == 6
    assert {f.severity for f in findings} == {"critical"}
    assert len({f.id for f in findings}) == 6
    for f in findings:
        excerpt = f.evidence[0].excerpt
        assert "****" in excerpt or set(excerpt) == {"*"}
        assert AWS not in excerpt and GOOGLE not in excerpt
    assert mask(AWS) == "AKIA****MNOP"


def test_secrets_distinct_only(make_facts, run_id):
    assert len(check_hardcoded_secrets(make_facts(strings=[AWS, AWS, f"x{AWS}"]), run_id)) == 1


def test_secrets_negative(make_facts, run_id):
    strings = ["AKIAshort", "AIza123", "sk_test_" + "a" * 30, "hello world"]
    assert check_hardcoded_secrets(make_facts(strings=strings), run_id) == []


def test_exported_component_positive_severities(make_facts, run_id):
    comps = [
        Component("service", "com.example.app.Svc", exported=True),
        Component("provider", "com.example.app.Prov", exported=True),
    ]
    findings = check_exported_components(make_facts(components=comps), run_id)
    assert {f.severity for f in findings} == {"medium", "high"}
    sev = {f.title.split(": ")[1]: f.severity for f in findings}
    assert sev["com.example.app.Prov"] == "high" and sev["com.example.app.Svc"] == "medium"


def test_exported_launcher_and_deep_link_activities_not_flagged(make_facts, run_id):
    comps = [
        Component("activity", "com.example.app.Alias", exported=True, has_intent_filter=True, launcher=True),
        Component("activity", "com.example.app.Link", exported=True, has_intent_filter=True, deep_link=True),
    ]
    assert check_exported_components(make_facts(components=comps), run_id) == []


def test_exported_filtered_activity_is_low(make_facts, run_id):
    comps = [Component("activity", "com.example.app.Share", exported=True, has_intent_filter=True)]
    (f,) = check_exported_components(make_facts(components=comps), run_id)
    assert f.severity == "low"


def test_exported_component_negative(make_facts, run_id):
    comps = [
        Component("activity", "com.example.app.Main", exported=True, has_intent_filter=True),
        Component("service", "com.example.app.Guarded", exported=True, permission="com.x.PERM"),
        Component("receiver", "com.example.app.Private", exported=False),
        Component("receiver", "com.example.app.Unknown", exported=None),
    ]
    assert check_exported_components(make_facts(components=comps), run_id) == []


def test_allow_backup_positive(make_facts, run_id):
    (f,) = check_allow_backup(make_facts(app_attrs={"allowBackup": "true"}), run_id)
    assert f.severity == "medium"
    (g,) = check_allow_backup(make_facts(app_attrs={}, target_sdk=30), run_id)
    assert "unset" in g.evidence[0].excerpt


def test_allow_backup_negative(make_facts, run_id):
    assert check_allow_backup(make_facts(app_attrs={"allowBackup": "false"}, target_sdk=30), run_id) == []
    assert check_allow_backup(make_facts(app_attrs={}, target_sdk=33), run_id) == []


def test_dangerous_permissions_medium_and_high(make_facts, run_id):
    p = "android.permission."
    (m,) = check_dangerous_permissions(make_facts(permissions=[p + "CAMERA", p + "INTERNET"]), run_id)
    assert m.severity == "medium" and m.evidence[0].excerpt == "CAMERA"
    four = [p + x for x in ("CAMERA", "READ_SMS", "RECORD_AUDIO", "READ_CONTACTS")]
    (h,) = check_dangerous_permissions(make_facts(permissions=four), run_id)
    assert h.severity == "high"


def test_dangerous_permissions_negative(make_facts, run_id):
    perms = ["android.permission.INTERNET", "android.permission.VIBRATE"]
    assert check_dangerous_permissions(make_facts(permissions=perms), run_id) == []


def test_http_urls_positive_capped(make_facts, run_id):
    strings = [f"http://api{i}.example.com/v1" for i in range(15)]
    (f,) = check_http_urls(make_facts(strings=strings), run_id)
    assert f.severity == "low" and len(f.evidence) == 10


def test_http_urls_negative(make_facts, run_id):
    strings = [
        "https://example.com",
        "http://localhost:8080/x",
        "http://127.0.0.1/x",
        "http://schemas.android.com/apk/res/android",
        "http://*/*",
        "http://wifi-not-enabled",
        "http://ns.adobe.com/xap/1.0/",
        "http://xml.org/sax/features/namespaces",
    ]
    assert check_http_urls(make_facts(strings=strings), run_id) == []


def test_webview_bridge_positive(make_facts, run_id):
    (f,) = check_webview_js_bridge(make_facts(uses_webview_js=True), run_id)
    assert f.severity == "medium" and f.rule_id == "sec.webview_js_bridge"


def test_webview_bridge_negative(make_facts, run_id):
    assert check_webview_js_bridge(make_facts(), run_id) == []
