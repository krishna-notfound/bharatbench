"""Dynamic security checks run once per job on the (rooted) redroid device, after the journeys.

Every check returns a HarnessSecurityCheck. A check that cannot run says why in `note` (ran=False) and never
produces a finding. Secrets are always masked (first 4 + last 4 chars) before they reach any output.
"""

import asyncio
import ipaddress
import itertools
import logging
import re
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ClassVar

from .adb import Adb
from .manifest import Component, parse_components
from .models import HarnessSecurityCheck, HarnessSecurityEvidence
from .parsers import _app_pids, _line_pid, parse_logcat, parse_resumed_activity

log = logging.getLogger("harness.security")

Sleep = Callable[[float], Awaitable[None]]

MAX_EVIDENCE = 10
_SEV = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# ---------------------------------------------------------------- masking + secret patterns

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")
_BEARER = re.compile(r"Bearer\s+([A-Za-z0-9._~+/=-]{16,})")
_APIKEY = re.compile(r"AIza[0-9A-Za-z_-]{35}|AKIA[0-9A-Z]{16}|sk_live_[0-9A-Za-z]{16,}|ghp_[0-9A-Za-z]{30,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\w.])(?:\+91[\s-]?)?[6-9]\d{9}(?![\w.])")
_KV = re.compile(
    r"""(?ix)(password|passwd|pwd|passcode|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token
    |token|\botp)["']?\s*[:=]\s*["']?([^\s"',;&<>]{4,})"""
)
_PREF_ENTRY = re.compile(r'<(?:string|int|long)\s+name="([^"]+)"[^>]*?(?:value="([^"]*)"\s*/>|>([^<]*)</)')
_SENSITIVE_KEY = {"password", "passwd", "pwd", "passcode", "secret", "token", "apikey", "otp", "pin", "cvv"}
_SENSITIVE_PAIRS = {("api", "key"), ("access", "token"), ("auth", "token"), ("card", "number"), ("session", "id")}
_PLACEHOLDERS = {"null", "none", "true", "false", "undefined", "empty", "changeme"}


def mask(value: str) -> str:
    """Keep first 4 + last 4 characters; anything 8 chars or shorter is fully hidden."""
    v = value.strip()
    return v[:4] + "…" + v[-4:] if len(v) > 8 else "****"


def _tokens(name: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", name)]


def is_sensitive_name(name: str) -> bool:
    toks = _tokens(name)
    return any(t in _SENSITIVE_KEY for t in toks) or any(p in _SENSITIVE_PAIRS for p in itertools.pairwise(toks))


def _mask_in(text: str, spans: list[re.Pattern[str]]) -> str:
    for rx in spans:
        text = rx.sub(lambda m: mask(m.group(0)), text)
    return text


def scan_secrets(text: str) -> list[tuple[str, str, str]]:
    """(kind, severity, masked match) for free text. kind: jwt | bearer | api_key | credential | email | phone."""
    hits: list[tuple[str, str, str]] = []
    for m in _JWT.finditer(text):
        hits.append(("jwt", "high", mask(m.group(0))))
    for m in _BEARER.finditer(text):
        hits.append(("bearer", "high", "Bearer " + mask(m.group(1))))
    for m in _APIKEY.finditer(text):
        hits.append(("api_key", "high", mask(m.group(0))))
    for m in _KV.finditer(text):
        val = m.group(2)
        if val.lower() not in _PLACEHOLDERS and not val.startswith("eyJ"):
            hits.append(("credential", "high", f"{m.group(1)}={mask(val)}"))
    for m in _EMAIL.finditer(text):
        hits.append(("email", "medium", mask(m.group(0))))
    for m in _PHONE.finditer(text):
        hits.append(("phone", "medium", mask(m.group(0))))
    return hits


def scan_prefs_xml(text: str) -> list[tuple[str, str, str]]:
    """shared_prefs XML: sensitive-named keys with real values, plus pattern hits inside any value."""
    hits: list[tuple[str, str, str]] = []
    for m in _PREF_ENTRY.finditer(text):
        key, val = m.group(1), (m.group(2) if m.group(2) is not None else m.group(3)) or ""
        val = val.strip()
        if not val:
            continue
        if is_sensitive_name(key) and len(val) >= 4 and val.lower() not in _PLACEHOLDERS:
            hits.append(("credential", "high", f"{key}={mask(val)}"))
            continue
        for kind, sev, masked in scan_secrets(val):
            if kind != "credential":
                hits.append((kind, sev, f"{key}: {masked}"))
    return hits


def _worst(*sevs: str) -> str:
    return max(sevs, key=lambda s: _SEV[s]) if sevs else "low"


def _ev(kind: str, ref: str | None = None, excerpt: str | None = None) -> HarnessSecurityEvidence:
    return HarnessSecurityEvidence(kind=kind, ref=ref, excerpt=excerpt)  # type: ignore[arg-type]


def not_run(check_id: str, title: str, why: str) -> HarnessSecurityCheck:
    return HarnessSecurityCheck(id=check_id, title=title, passed=True, ran=False, note=f"Not run: {why}")


# ---------------------------------------------------------------- logcat leak scan


def scan_logcat_leaks(logs: dict[str, str], package: str) -> HarnessSecurityCheck:
    """`logs` maps relative artifact path -> logcat text. Only lines from the app's own pid(s) are scanned."""
    title = "Secrets or personal data written to logcat"
    if not logs:
        return not_run("sec.logcat_leaks", title, "no logcat was captured")
    ev: list[HarnessSecurityEvidence] = []
    seen: set[str] = set()
    sev = "low"
    scanned = 0
    for ref, text in logs.items():
        lines = text.splitlines()
        pids = _app_pids(lines, package)
        if not pids:
            continue
        for ln in lines:
            if _line_pid(ln) not in pids:
                continue
            scanned += 1
            hits = scan_secrets(ln)
            otp = re.search(r"(?i)\botp\b[^\n]{0,24}?(\d{4,8})\b", ln)
            if otp:
                hits.append(("otp", "high", "otp=" + mask(otp.group(1))))
            for kind, s, masked in hits:
                key = f"{kind}:{masked}"
                if key in seen or len(ev) >= MAX_EVIDENCE:
                    continue
                seen.add(key)
                sev = _worst(sev, s)
                tag = ln.split(":", 1)[0][-40:].strip()
                ev.append(_ev("logcat", ref, f"{kind} in log ({tag}): {masked}"))
    if scanned == 0:
        return not_run(
            "sec.logcat_leaks", title, "the app's process id could not be identified in the captured logcat"
        )
    if not ev:
        return HarnessSecurityCheck(id="sec.logcat_leaks", title=title, note=f"Scanned {scanned} app log lines.")
    return HarnessSecurityCheck(
        id="sec.logcat_leaks", title=title, passed=False, severity=sev, evidence=ev,  # type: ignore[arg-type]
        note=f"{len(ev)} distinct leak(s) in {scanned} app log lines. Values are masked.",
    )  # fmt: skip


# ---------------------------------------------------------------- cleartext traffic (tcpdump)

_TD_HEAD = re.compile(
    r"^\d\d:\d\d:\d\d\.\d+\s+\S+\s+\S+\s+IP\s+(\d+\.\d+\.\d+\.\d+)\.\d+\s+>\s+(\d+\.\d+\.\d+\.\d+)\.80:\s+Flags\s+\[([^\]]*)\]"
    r".*?length\s+(\d+)"
)
_REQ_LINE = re.compile(r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(\S+)\s+HTTP/1\.[01]")


def _is_local(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    return a.is_private or a.is_loopback or a.is_link_local


def parse_tcpdump(text: str, container_ip: str | None) -> list[tuple[str, str, str]]:
    """Plain-HTTP requests to non-local hosts: (host or ip, "METHOD path", dest ip). Path query strings are dropped."""
    out: list[tuple[str, str, str]] = []
    cur: tuple[str, int] | None = None  # (dst ip, payload length) of the packet being read
    pending: tuple[str, str, str] | None = None
    syn_only: dict[str, None] = {}
    seen: set[tuple[str, str]] = set()

    def flush() -> None:
        nonlocal pending
        if pending and (pending[0], pending[1]) not in seen:
            seen.add((pending[0], pending[1]))
            out.append(pending)
        pending = None

    for ln in text.splitlines():
        m = _TD_HEAD.match(ln)
        if m:
            flush()
            src, dst, flags, length = m.group(1), m.group(2), m.group(3), int(m.group(4))
            if (container_ip and src != container_ip) or _is_local(dst):
                cur = None
                continue
            cur = (dst, length)
            if "S" in flags and "." not in flags and length == 0:
                syn_only[dst] = None
            continue
        if cur is None:
            continue
        # payload lines follow the header (tcpdump -A); the request line may be glued to binary header bytes
        rq = re.search(r"(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(\S+)\s+HTTP/1\.[01]", ln)
        if rq and cur[1] > 0:
            flush()
            path = rq.group(2).split("?", 1)[0]
            pending = (cur[0], f"{rq.group(1)} {path}", cur[0])
        elif ln.startswith("Host:") and pending is not None:
            host = ln.split(":", 1)[1].strip().split(":")[0]
            pending = (host or pending[0], pending[1], pending[2])
    flush()
    reported = {o[2] for o in out}
    for dst in syn_only:  # connection attempts whose payload was not captured
        if dst not in reported:
            out.append((dst, "connection to port 80", dst))
    return out


def cleartext_check(hits: list[tuple[str, str, str]] | None, why_not: str | None) -> HarnessSecurityCheck:
    title = "Plain HTTP (cleartext) traffic observed"
    if hits is None:
        return not_run("sec.cleartext_traffic", title, why_not or "no packet capture was taken")
    if not hits:
        return HarnessSecurityCheck(
            id="sec.cleartext_traffic", title=title,
            note="No plain HTTP (port 80) traffic to non-local hosts during the baseline journey.",
        )  # fmt: skip
    ev = [_ev("note", None, f"{req} to {host}") for host, req, _ in hits[:MAX_EVIDENCE]]
    return HarnessSecurityCheck(
        id="sec.cleartext_traffic", title=title, passed=False, severity="high", evidence=ev,
        note=f"{len(hits)} plain HTTP destination(s) seen on the wire during the baseline journey.",
    )  # fmt: skip


class CleartextCapture:
    """`sudo -n timeout N tcpdump -i any ... tcp dst port 80` for the baseline journey (fixed argv; see sudoers)."""

    ARGS = ("-i", "any", "-nn", "-A", "-s", "1024", "-l", "tcp", "dst", "port", "80")
    MAX_SECONDS = 240

    def __init__(self, sudo: str, tcpdump: str, timeout_bin: str, out_file: Path) -> None:
        self.argv = [sudo, "-n", timeout_bin, str(self.MAX_SECONDS), tcpdump, *self.ARGS]
        self.out_file = out_file
        self._proc: asyncio.subprocess.Process | None = None
        self.error: str | None = None

    async def start(self) -> None:
        try:
            self.out_file.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.out_file.open("wb")
            self._proc = await asyncio.create_subprocess_exec(
                *self.argv, stdin=asyncio.subprocess.DEVNULL, stdout=self._fh, stderr=asyncio.subprocess.DEVNULL
            )
            await asyncio.sleep(1.0)  # let tcpdump open the interface
            if self._proc.returncode is not None:
                self.error = f"tcpdump exited immediately (rc={self._proc.returncode}); sudoers entry missing?"
                self._proc = None
        except (OSError, FileNotFoundError) as exc:
            self.error = f"could not start tcpdump: {exc}"
            self._proc = None

    async def stop(self) -> str | None:
        """Stop the capture and return its text (deleted from disk afterwards: it may hold sensitive payloads)."""
        if self._proc is None:
            return None
        await asyncio.sleep(1.0)  # flush the last packets
        try:
            self._proc.terminate()
        except (ProcessLookupError, PermissionError):
            pass  # `timeout` ends it anyway
        try:
            await asyncio.wait_for(self._proc.wait(), 5)
        except TimeoutError:
            pass
        self._fh.close()
        try:
            text = self.out_file.read_text("utf-8", "replace")
        finally:
            self.out_file.unlink(missing_ok=True)
        return text


# ---------------------------------------------------------------- on-device checks


class ProbeResult:
    def __init__(self, crash: str = "") -> None:
        self.crash = crash
        self.opened = False
        self.screenshot: bytes | None = None


class DeviceAudit:
    def __init__(self, adb: Adb, package: str, job_dir: Path, apk: Path, sleep: Sleep = asyncio.sleep) -> None:
        self.adb, self.pkg, self.job_dir, self.apk, self._sleep = adb, package, job_dir, apk, sleep
        self.root = f"/data/data/{package}"

    async def _sh(self, cmd: str, timeout: float = 30) -> tuple[int, str]:
        rc, out, _ = await self.adb.shell(cmd, timeout=timeout)
        return rc, out

    async def ensure_root(self) -> bool:
        rc, out = await self._sh("id -u", 10)
        if rc == 0 and out.strip() == "0":
            return True
        await self.adb.run(["root"], timeout=20)
        await self._sleep(2)
        await self.adb.global_run(["connect", self.adb.serial], timeout=15)  # adbd restarts; tcp devices reconnect
        rc, out = await self._sh("id -u", 10)
        return rc == 0 and out.strip() == "0"

    # --- 1. private storage
    async def storage(self) -> list[HarnessSecurityCheck]:
        t_sec = "Secrets or personal data stored in plaintext"
        t_db = "Unencrypted database with sensitive columns"
        t_wr = "World-readable app files"
        ids = ("sec.storage_secrets", "sec.storage_db", "sec.world_readable")
        titles = (t_sec, t_db, t_wr)
        if not await self.ensure_root():
            return [not_run(i, t, "adb root is not available on this device") for i, t in zip(ids, titles, strict=True)]
        rc, _ = await self._sh(f"ls -d {shlex.quote(self.root)}", 10)
        if rc != 0:
            return [not_run(i, t, "the app's data directory does not exist") for i, t in zip(ids, titles, strict=True)]
        return [await self._secrets(), await self._databases(), await self._world_readable()]

    async def _find(self, sub: str, extra: str = "") -> list[str]:
        base = shlex.quote(f"{self.root}/{sub}")
        _, out = await self._sh(f"find {base} -type f {extra} 2>/dev/null | head -200", 30)
        return [ln.strip() for ln in out.splitlines() if ln.strip().startswith(self.root)]

    async def _secrets(self) -> HarnessSecurityCheck:
        title = "Secrets or personal data stored in plaintext"
        ev: list[HarnessSecurityEvidence] = []
        sev, scanned = "low", 0
        prefs = [p for p in await self._find("shared_prefs") if p.endswith(".xml")][:60]
        files = [
            p for p in await self._find("files", '-size -200k ! -name "*.png" ! -name "*.jpg" ! -name "*.apk"')
        ][:40]
        for path in prefs + files:
            rc, text = await self._sh(f"head -c 200000 {shlex.quote(path)}", 20)
            if rc != 0:
                continue
            scanned += 1
            rel = path[len(self.root) + 1 :]
            hits = scan_prefs_xml(text) if path.endswith(".xml") and "shared_prefs/" in path else scan_secrets(text)
            for kind, s, masked in hits:
                if len(ev) < MAX_EVIDENCE:
                    sev = _worst(sev, s)
                    ev.append(_ev("note", None, f"{rel}: {kind} {masked}"))
        if not ev:
            return HarnessSecurityCheck(
                id="sec.storage_secrets", title=title,
                note=f"Scanned {scanned} files (shared_prefs, files); no plaintext secrets matched.",
            )  # fmt: skip
        return HarnessSecurityCheck(
            id="sec.storage_secrets", title=title, passed=False, severity=sev, evidence=ev,  # type: ignore[arg-type]
            note=f"{len(ev)} match(es) in {scanned} scanned files. Values are masked.",
        )  # fmt: skip

    async def _databases(self) -> HarnessSecurityCheck:
        title = "Unencrypted database with sensitive columns"
        dbs = [
            p for p in await self._find("databases")
            if not re.search(r"-(wal|shm|journal)$", p)
        ][:15]  # fmt: skip
        ev: list[HarnessSecurityEvidence] = []
        checked = unencrypted = 0
        for db in dbs:
            q = shlex.quote(db)
            _, head = await self._sh(f"head -c 15 {q}", 10)
            if head.strip() != "SQLite format 3":
                checked += 1  # encrypted (or not a SQLite file): nothing to read
                continue
            checked += 1
            unencrypted += 1
            sql = (
                "SELECT m.name || '|' || p.name FROM sqlite_master m JOIN pragma_table_info(m.name) p "
                "WHERE m.type='table';"
            )
            rc, cols = await self._sh(f"sqlite3 -readonly {q} {shlex.quote(sql)}", 30)
            if rc != 0:
                continue
            for line in cols.splitlines():
                tbl, _, col = line.strip().partition("|")
                if not (re.fullmatch(r"\w{1,64}", tbl) and re.fullmatch(r"\w{1,64}", col)):
                    continue
                if not is_sensitive_name(col):
                    continue
                cnt_sql = f'SELECT count(*) FROM "{tbl}" WHERE "{col}" IS NOT NULL AND "{col}" != \'\';'
                rc, cnt = await self._sh(f"sqlite3 -readonly {q} {shlex.quote(cnt_sql)}", 30)
                n = int(cnt.strip()) if rc == 0 and cnt.strip().isdigit() else 0
                if n > 0 and len(ev) < MAX_EVIDENCE:
                    name = db.rsplit("/", 1)[-1]
                    ev.append(_ev("note", None, f"{name}: column {tbl}.{col} holds {n} non-empty value(s), unencrypted"))
        if not dbs:
            return HarnessSecurityCheck(id="sec.storage_db", title=title, note="The app has no SQLite databases.")
        if not ev:
            return HarnessSecurityCheck(
                id="sec.storage_db", title=title,
                note=f"{checked} database(s) checked ({unencrypted} unencrypted); no populated sensitive columns.",
            )  # fmt: skip
        return HarnessSecurityCheck(
            id="sec.storage_db", title=title, passed=False, severity="high", evidence=ev,
            note="Row values are not included; only column names and counts.",
        )  # fmt: skip

    async def _world_readable(self) -> HarnessSecurityCheck:
        title = "World-readable app files"
        files = [
            f.replace("//", "/") for f in await self._find("", "-perm -o+r ! -path '*/lib/*'")
        ]  # fmt: skip
        if not files:
            return HarnessSecurityCheck(
                id="sec.world_readable", title=title, note="No files in the app's data dir are readable by other apps."
            )  # fmt: skip
        sensitive = [f for f in files if "/shared_prefs/" in f or "/databases/" in f]
        ev = [_ev("note", None, f"{f[len(self.root) + 1 :]} is world-readable") for f in files[:MAX_EVIDENCE]]
        return HarnessSecurityCheck(
            id="sec.world_readable", title=title, passed=False, severity="medium" if sensitive else "low",
            evidence=ev, note=f"{len(files)} world-readable file(s) found.",
        )  # fmt: skip

    # --- 5. debuggable
    async def debuggable(self) -> HarnessSecurityCheck:
        title = "App is debuggable"
        rc, out = await self._sh(f"run-as {shlex.quote(self.pkg)} id", 15)
        run_as = rc == 0 and "uid=" in out
        _, dump = await self._sh(f"dumpsys package {shlex.quote(self.pkg)} | grep -m1 pkgFlags", 20)
        flag = "DEBUGGABLE" in dump
        if run_as or flag:
            ev = [_ev("note", None, "run-as succeeded for the app's uid" if run_as else dump.strip()[:200])]
            return HarnessSecurityCheck(
                id="sec.debuggable", title=title, passed=False, severity="high", evidence=ev,
                note="Anyone with adb can read this app's private data; release builds must not be debuggable.",
            )  # fmt: skip
        return HarnessSecurityCheck(
            id="sec.debuggable", title=title, note="run-as is refused and the package is not flagged DEBUGGABLE."
        )  # fmt: skip

    # --- 3. exported components
    # Destructive-sounding component names are never probed. Keep in step with parsers.DENYLIST (UI labels).
    _RISKY = re.compile(r"(?i)panic|wipe|delete|remove|logout|signout|reset|uninstall|pay|purchase|checkout|erase|clear")
    MAX_PROBES: ClassVar[dict[str, int]] = {"activity": 6, "service": 4, "receiver": 4}

    async def exported(self) -> HarnessSecurityCheck:
        title = "Exported components reachable by other apps"
        try:
            _, comps = parse_components(self.apk)
        except Exception as exc:  # noqa: BLE001 - unreadable manifest -> honest 'not run'
            return not_run("sec.exported_components", title, f"could not read the APK manifest ({type(exc).__name__})")
        cand = [c for c in comps if not c.launcher and c.permission is None]
        skipped_risky = [c.name for c in cand if self._RISKY.search(c.name.rsplit(".", 1)[-1])]
        cand = [c for c in cand if c.name not in skipped_risky]
        if not cand:
            return HarnessSecurityCheck(
                id="sec.exported_components", title=title,
                note=f"No unprotected exported components besides the launcher ({len(comps)} exported in total).",
            )  # fmt: skip
        ev: list[HarnessSecurityEvidence] = []
        crashed = opened = probed = 0
        shot_n = 0
        quota = dict(self.MAX_PROBES)
        for c in cand:
            if quota[c.kind] <= 0:
                continue
            quota[c.kind] -= 1
            probed += 1
            res = await self._probe(c)
            if res.crash:
                crashed += 1
                ev.append(_ev("logcat", None, f"{c.kind} {c.name} crashed the app when started without extras: {res.crash}"))
            elif res.opened and c.kind == "activity" and not c.has_filter:
                opened += 1
                ref = None
                if res.screenshot:
                    shot_n += 1
                    ref = self._save_shot(shot_n, res.screenshot)
                ev.append(
                    _ev("screenshot" if ref else "note", ref, f"activity {c.name} opens directly for any app (no login or permission gate)")
                )
        await self.adb.shell("am", "force-stop", self.pkg, timeout=20)
        await self.adb.shell("input", "keyevent", "KEYCODE_HOME", timeout=10)
        note = f"Probed {probed} of {len(cand)} unprotected exported component(s) with no extras."
        if skipped_risky:
            note += f" Skipped for safety (destructive-sounding names): {', '.join(skipped_risky[:5])}."
        if not ev:
            return HarnessSecurityCheck(id="sec.exported_components", title=title, note=note)
        sev = "medium" if crashed else "low"
        return HarnessSecurityCheck(
            id="sec.exported_components", title=title, passed=False, severity=sev, evidence=ev[:MAX_EVIDENCE],  # type: ignore[arg-type]
            note=note,
        )  # fmt: skip

    def _save_shot(self, n: int, png: bytes) -> str:
        d = self.job_dir / "security"
        d.mkdir(parents=True, exist_ok=True)
        rel = f"security/export_{n}.png"
        (self.job_dir / rel).write_bytes(png)
        return rel

    async def _launch_main(self) -> None:
        _, out, _ = await self.adb.shell(
            "cmd", "package", "resolve-activity", "--brief", "-c", "android.intent.category.LAUNCHER", shlex.quote(self.pkg),
            timeout=20,
        )  # fmt: skip
        comp = out.strip().splitlines()[-1].strip() if out.strip() else ""
        if "/" in comp:
            await self.adb.shell("am", "start", "-W", "-n", shlex.quote(comp), timeout=30)

    async def _probe(self, c: Component) -> ProbeResult:
        pkg = self.pkg
        comp = shlex.quote(f"{pkg}/{c.name}")  # c.name comes from the (untrusted) APK manifest
        await self.adb.shell("am", "force-stop", pkg, timeout=20)
        await self.adb.run(["logcat", "-c"], timeout=20)
        if c.kind == "activity":
            await self.adb.shell("am", "start", "-W", "-n", comp, timeout=30)
        else:
            # background-start limits apply to shell too, so bring the app to the foreground first
            await self._launch_main()
            await self._sleep(2)
            await self.adb.run(["logcat", "-c"], timeout=20)
            if c.kind == "service":
                await self.adb.shell("am", "startservice", "-n", comp, timeout=30)
            else:
                await self.adb.shell("am", "broadcast", "-n", comp, timeout=30)
        await self._sleep(2)
        _, log_text, _ = await self.adb.run(["logcat", "-d", "-v", "threadtime"], timeout=60)
        crashes, _ = parse_logcat(log_text, pkg)
        crash = ""
        if crashes:
            first = next((ln for ln in crashes[0].excerpt.splitlines() if "Exception" in ln or "Error" in ln), "")
            crash = first.split(": ", 1)[-1][:160] or crashes[0].type
        res = ProbeResult(crash=crash)
        if c.kind == "activity" and not crash:
            _, act, _ = await self.adb.shell("dumpsys activity activities | grep -m1 mResumedActivity", timeout=30)
            resumed = parse_resumed_activity(act.replace("mResumedActivity:", "ResumedActivity"))
            res.opened = bool(resumed and resumed.startswith(pkg + "/"))
            if res.opened:
                rc, png = await self.adb.run_bytes(["exec-out", "screencap", "-p"], timeout=30)
                if rc == 0 and png[:4] == b"\x89PNG":
                    res.screenshot = png
        return res
