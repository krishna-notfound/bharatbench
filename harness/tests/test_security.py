import struct
import zipfile

from harness.adb import Adb
from harness.manifest import parse_components
from harness.security import (
    DeviceAudit,
    cleartext_check,
    is_sensitive_name,
    mask,
    parse_tcpdump,
    scan_logcat_leaks,
    scan_prefs_xml,
    scan_secrets,
)

from .conftest import FakeRunner

PKG = "com.example.shop"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijk"


def test_mask_keeps_first_and_last_four():
    assert mask("abcdefghijkl") == "abcd…ijkl"
    assert mask("short") == "****"


def test_sensitive_names_are_tokenised():
    assert is_sensitive_name("userPassword") and is_sensitive_name("auth_token") and is_sensitive_name("API_KEY")
    assert is_sensitive_name("otp") and not is_sensitive_name("footprint") and not is_sensitive_name("author")


def test_prefs_xml_secrets_masked_and_theme_ignored():
    xml = (
        f'<map><string name="auth_token">{JWT}</string><string name="email">jane.doe@example.com</string>'
        '<string name="theme">dark</string><string name="password"></string></map>'
    )
    hits = scan_prefs_xml(xml)
    assert {h[0] for h in hits} == {"credential", "email"}
    blob = " ".join(h[2] for h in hits)
    assert JWT not in blob and "jane.doe@example.com" not in blob and "eyJh…hijk" in blob


def test_scan_secrets_kinds():
    kinds = {h[0] for h in scan_secrets(f"Authorization: Bearer abcdefghijklmnop1234 {JWT} call +91 98765 43210 9876543210")}
    assert {"bearer", "jwt", "phone"} <= kinds
    assert scan_secrets("nothing to see here, version=1.2.3") == []


LOG = (
    f"11-21 17:46:10.000   500   500 I ActivityManager: Start proc 4242:{PKG}/u0a77 for activity\n"
    f"11-21 17:46:11.000  4242  4242 D LoginVM: login ok token={JWT}\n"
    "11-21 17:46:12.000  4242  4242 D Net: password=hunter2hunter2 user jane.doe@example.com\n"
    "11-21 17:46:13.000  4242  4242 D Sms: otp is 483920\n"
    "11-21 17:46:14.000  9999  9999 D Other: token=zzzzzzzzzzzzzzzz not ours\n"
)


def test_logcat_leaks_only_app_pid_masked():
    chk = scan_logcat_leaks({"logcat/baseline.txt": LOG}, PKG)
    assert chk.ran and not chk.passed and chk.severity == "high"
    text = " ".join(e.excerpt or "" for e in chk.evidence)
    assert JWT not in text and "hunter2hunter2" not in text and "zzzz" not in text
    assert "otp" in text and chk.evidence[0].ref == "logcat/baseline.txt"


def test_logcat_clean_and_not_run():
    clean = f"11-21 17:46:10.000   500   500 I ActivityManager: Start proc 4242:{PKG}/u0a77 for x\n"
    clean += "11-21 17:46:11.000  4242  4242 D App: hello\n"
    assert scan_logcat_leaks({"a": clean}, PKG).passed
    assert not scan_logcat_leaks({}, PKG).ran
    assert not scan_logcat_leaks({"a": "11-21 17:46:11.000  1  1 D App: hello"}, PKG).ran  # no pid known


TCPDUMP = """\
17:48:41.391 veth5ae5bd0 P   IP 172.17.0.2.40202 > 142.251.150.120.80: Flags [P.], seq 0:86, ack 1, win 4095, length 86
E..~..@.@..(.......x.P....
GET /generate_204?token=abc HTTP/1.1
Host: connectivitycheck.gstatic.com
Connection: close

17:48:41.391 docker0 In  IP 172.17.0.2.40202 > 142.251.150.120.80: Flags [P.], seq 0:86, ack 1, win 4095, length 86
GET /generate_204?token=abc HTTP/1.1
Host: connectivitycheck.gstatic.com

17:48:41.391 ens5  Out IP 172.31.33.194.40202 > 142.251.150.120.80: Flags [P.], seq 0:86, ack 1, win 4095, length 86
GET /generate_204?token=abc HTTP/1.1
Host: connectivitycheck.gstatic.com

17:48:42.000 veth5ae5bd0 P   IP 172.17.0.2.40300 > 34.223.124.45.80: Flags [S], seq 1, win 65535, length 0
17:48:43.000 veth5ae5bd0 P   IP 172.17.0.2.40301 > 10.0.0.5.80: Flags [P.], seq 0:50, ack 1, win 4095, length 50
GET /internal HTTP/1.1
Host: intranet.local
"""


def test_tcpdump_parse_dedupes_drops_query_and_local():
    hits = parse_tcpdump(TCPDUMP, "172.17.0.2")
    assert ("connectivitycheck.gstatic.com", "GET /generate_204", "142.251.150.120") in hits
    assert ("34.223.124.45", "connection to port 80", "34.223.124.45") in hits
    assert len(hits) == 2  # NAT copy deduped, 10.x local host ignored, query string (token) dropped
    chk = cleartext_check(hits, None)
    assert not chk.passed and chk.severity == "high" and "token=abc" not in str(chk.evidence)


def test_cleartext_not_run_and_clean():
    assert not cleartext_check(None, "tcpdump did not start").ran
    assert cleartext_check([], None).passed


# ---- manifest (hand-built binary XML) ----


def _axml(pkg: str, comps: list[tuple[str, str, dict[str, object], list[str]]]) -> bytes:
    strings: list[str] = []

    def sid(x: str) -> int:
        if x not in strings:
            strings.append(x)
        return strings.index(x)

    def start(tag: str, attrs: list[tuple[str, object]]) -> bytes:
        body = b"".join(
            struct.pack("<iiiHBBI", -1, sid(k), sid(v) if isinstance(v, str) else -1, 8, 0,
                        0x03 if isinstance(v, str) else 0x12, sid(v) if isinstance(v, str) else (0xFFFFFFFF if v else 0))
            for k, v in attrs
        )  # fmt: skip
        return struct.pack("<HHIIIIIHHHHHH", 0x0102, 16, 36 + len(body), 1, 0xFFFFFFFF, 0xFFFFFFFF,
                           sid(tag), 20, 20, len(attrs), 0, 0, 0) + body  # fmt: skip

    def end(tag: str) -> bytes:
        return struct.pack("<HHIIIII", 0x0103, 16, 24, 1, 0xFFFFFFFF, 0xFFFFFFFF, sid(tag))

    chunks = [start("manifest", [("package", pkg)]), start("application", [])]
    for kind, name, attrs, cats in comps:
        chunks.append(start(kind, [("name", name), *attrs.items()]))
        if cats:
            chunks.append(start("intent-filter", []))
            for c in cats:
                chunks.append(start("category", [("name", c)]))
                chunks.append(end("category"))
            chunks.append(end("intent-filter"))
        chunks.append(end(kind))
    chunks += [end("application"), end("manifest")]
    body = b"".join(chunks)
    enc = [s.encode("utf-16-le") for s in strings]
    pool_data, offs = b"", []
    for s, e in zip(strings, enc, strict=True):
        offs.append(len(pool_data))
        pool_data += struct.pack("<H", len(s)) + e + b"\x00\x00"
    pool_data += b"\x00" * (-len(pool_data) % 4)
    hdr = 28 + 4 * len(strings)
    pool = struct.pack("<HHIIIIII", 0x0001, 28, hdr + len(pool_data), len(strings), 0, 0, hdr, 0)
    pool += b"".join(struct.pack("<I", o) for o in offs) + pool_data
    return struct.pack("<HHI", 0x0003, 8, 8 + len(pool) + len(body)) + pool + body


def test_manifest_exported_rules(tmp_path):
    comps = [
        ("activity", ".Main", {}, ["android.intent.category.LAUNCHER"]),
        ("activity", ".Hidden", {"exported": False}, []),
        ("activity", ".Open", {"exported": True}, []),
        ("service", "com.other.Svc", {}, []),  # no filter, no attr -> not exported
        ("receiver", ".Rx", {"permission": "com.x.PERM"}, ["android.intent.category.DEFAULT"]),
    ]
    apk = tmp_path / "a.apk"
    with zipfile.ZipFile(apk, "w") as z:
        z.writestr("AndroidManifest.xml", _axml(PKG, comps))
    pkg, found = parse_components(apk)
    assert pkg == PKG
    by = {c.name: c for c in found}
    assert set(by) == {f"{PKG}.Main", f"{PKG}.Open", f"{PKG}.Rx"}
    assert by[f"{PKG}.Main"].launcher and not by[f"{PKG}.Open"].has_filter
    assert by[f"{PKG}.Rx"].permission == "com.x.PERM"


# ---- on-device checks with a scripted adb ----


def audit(tmp_path, responses):
    runner = FakeRunner(responses)
    adb = Adb("adb", "127.0.0.1:5555", runner)
    return DeviceAudit(adb, PKG, tmp_path, tmp_path / "app.apk", sleep=_nosleep), runner


async def _nosleep(_s: float) -> None:
    return None


async def test_storage_audit_finds_plaintext_and_world_readable(tmp_path):
    root = f"/data/data/{PKG}"
    xml = f'<map><string name="auth_token">{JWT}</string></map>'
    a, _ = audit(
        tmp_path,
        {
            "id -u": (0, "0\n"),
            f"ls -d {root}": (0, root),
            f"find {root}/shared_prefs": (0, f"{root}/shared_prefs/s.xml\n"),
            f"find {root}/files": (0, ""),
            f"find {root}/databases": (0, f"{root}/databases/app.db\n"),
            "head -c 15": (0, "SQLite format 3"),
            "pragma_table_info": (0, "users|id\nusers|userPassword\nusers|name\n"),
            "SELECT count(*)": (0, "3\n"),
            f"head -c 200000 {root}/shared_prefs/s.xml": (0, xml),
            f"find {root}/ -type f": (0, f"{root}/shared_prefs/s.xml\n"),
        },
    )
    sec, db, wr = await a.storage()
    assert not sec.passed and sec.severity == "high" and JWT not in str(sec.evidence)
    assert not db.passed and "users.userPassword" in db.evidence[0].excerpt and "3 non-empty" in db.evidence[0].excerpt
    assert not wr.passed and wr.severity == "medium"


async def test_storage_audit_not_run_without_root(tmp_path):
    a, _ = audit(tmp_path, {"id -u": (0, "2000\n")})
    checks = await a.storage()
    assert [c.ran for c in checks] == [False, False, False]
    assert "root" in (checks[0].note or "")


async def test_debuggable_run_as(tmp_path):
    a, _ = audit(tmp_path, {"run-as": (0, "uid=10077(u0_a77) gid=10077\n")})
    assert not (await a.debuggable()).passed
    b, _ = audit(tmp_path, {"run-as": (1, "run-as: package not debuggable: com.example.shop\n")})
    assert (await b.debuggable()).passed


async def test_exported_probe_flags_crash_and_skips_risky(tmp_path):
    comps = [
        ("activity", ".Main", {}, ["android.intent.category.LAUNCHER"]),
        ("activity", ".Boom", {"exported": True}, []),
        ("activity", ".WipeDataActivity", {"exported": True}, []),
    ]
    with zipfile.ZipFile(tmp_path / "app.apk", "w") as z:
        z.writestr("AndroidManifest.xml", _axml(PKG, comps))
    crash = (
        f"11-21 17:46:10.000   500   500 I ActivityManager: Start proc 4242:{PKG}/u0a77 for activity\n"
        "11-21 17:46:11.000  4242  4242 E AndroidRuntime: FATAL EXCEPTION: main\n"
        f"11-21 17:46:11.000  4242  4242 E AndroidRuntime: Process: {PKG}, PID: 4242\n"
        "11-21 17:46:11.000  4242  4242 E AndroidRuntime: java.lang.NullPointerException: no extras\n"
    )
    a, runner = audit(tmp_path, {"logcat -d": (0, crash)})
    chk = await a.exported()
    assert not chk.passed and chk.severity == "medium"
    assert "NullPointerException" in chk.evidence[0].excerpt and ".Boom" in chk.evidence[0].excerpt
    assert "Skipped for safety" in (chk.note or "") and "WipeDataActivity" in (chk.note or "")
    started = [c for c in runner.calls if "am" in c and "start" in c]
    assert all("WipeData" not in " ".join(c) for c in started)


async def test_exported_not_run_on_bad_apk(tmp_path):
    (tmp_path / "app.apk").write_bytes(b"not a zip")
    a, _ = audit(tmp_path, {})
    assert not (await a.exported()).ran
