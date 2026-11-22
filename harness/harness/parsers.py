"""Pure parsers for adb/logcat/uiautomator text. No I/O."""

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .models import HarnessCrash

# Labels the crawler and the f23 agent must never tap. Keep in step with DeviceAudit._RISKY in security.py,
# which applies a similar safety filter to exported-component names for the dynamic security probes.
DENYLIST = (
    "logout", "log out", "sign out", "delete", "remove", "pay", "buy",
    "purchase", "checkout", "uninstall", "call", "sms",
)  # fmt: skip

NETWORK_ERRORS = (
    "SocketTimeoutException",
    "UnknownHostException",
    "ConnectException",
    "SSLHandshakeException",
    "java.io.IOException: unexpected end of stream",
)

_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


@dataclass(frozen=True)
class UiNode:
    cls: str
    text: str
    desc: str
    rid: str
    bounds: tuple[int, int, int, int]
    clickable: bool
    password: bool = False
    hint: str = ""
    enabled: bool = True

    @property
    def editable(self) -> bool:
        return self.cls.endswith(("EditText", "AutoCompleteTextView", "MultiAutoCompleteTextView"))

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def label(self) -> str:
        return self.text or self.desc or self.rid or f"{self.center[0]},{self.center[1]}"


def parse_ui_nodes(xml_text: str) -> list[UiNode]:
    start = xml_text.find("<hierarchy")
    if start < 0:
        return []
    try:
        root = ET.fromstring(xml_text[start:])
    except ET.ParseError:
        return []
    nodes: list[UiNode] = []
    for el in root.iter("node"):
        m = _BOUNDS.fullmatch(el.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = (int(g) for g in m.groups())
        nodes.append(
            UiNode(
                cls=el.get("class", ""),
                text=el.get("text", ""),
                desc=el.get("content-desc", ""),
                rid=el.get("resource-id", ""),
                bounds=(x1, y1, x2, y2),
                clickable=el.get("clickable") == "true",
                password=el.get("password") == "true",
                hint=el.get("hint", ""),
                enabled=el.get("enabled", "true") != "false",
            )
        )
    return nodes


def clickable_nodes(nodes: list[UiNode]) -> list[UiNode]:
    return [n for n in nodes if n.clickable and n.bounds[2] > n.bounds[0] and n.bounds[3] > n.bounds[1]]


def is_denied(node: UiNode) -> bool:
    haystack = f"{node.text} {node.desc} {node.rid.rsplit('/', 1)[-1]}".lower()
    return any(re.search(rf"\b{re.escape(w)}\b", haystack) for w in DENYLIST)


def visible_texts(nodes: list[UiNode]) -> set[str]:
    return {n.text.strip() for n in nodes if n.text.strip()}


def has_progress(nodes: list[UiNode]) -> bool:
    return any("ProgressBar" in n.cls for n in nodes)


def ui_hash(xml_text: str) -> str:
    return hashlib.sha1(xml_text.encode("utf-8", "replace")).hexdigest()


def parse_launch_time(out: str) -> int | None:
    if re.search(r"^Error|Status:\s*(error|timeout)", out, re.MULTILINE):
        return None
    m = re.search(r"TotalTime:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def parse_resumed_activity(out: str) -> str | None:
    m = re.search(r"ResumedActivity[^\n]*?\su\d+\s+(\S+/\S+)", out)
    return m.group(1).rstrip("}") if m else None


def parse_resolve_activity(out: str) -> str | None:
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if re.fullmatch(r"[\w.]+/[\w.$]+", line):
            return line
    return None


def normalize_activity(component: str | None, package: str) -> str | None:
    if not component or "/" not in component:
        return component
    pkg, act = component.split("/", 1)
    if act.startswith("."):
        act = pkg + act
    return f"{package if pkg == package else pkg}/{act}"


def parse_meminfo_pss(out: str) -> int | None:
    m = re.search(r"TOTAL PSS:\s*(\d+)", out) or re.search(r"^\s*TOTAL\s+(\d+)", out, re.MULTILINE)
    return int(m.group(1)) if m else None


def parse_df_free_kb(out: str) -> int | None:
    lines = [ln.split() for ln in out.strip().splitlines() if ln.strip()]
    for cols in reversed(lines):
        if len(cols) >= 4 and cols[3].isdigit():
            return int(cols[3])
    return None


_LOG_LINE = re.compile(r"^\d\d-\d\d\s+[\d:.]+\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+(.*?)\s*:\s?(.*)$")


def _app_pids(lines: list[str], package: str) -> set[str]:
    pids: set[str] = set()
    for ln in lines:
        if package not in ln:
            continue
        for rx in (r"Start proc (\d+):" + re.escape(package), r"PID:\s*(\d+)", r"pid (\d+) \(" + re.escape(package)):
            m = re.search(rx, ln)
            if m:
                pids.add(m.group(1))
    return pids


def _line_pid(ln: str) -> str | None:
    m = _LOG_LINE.match(ln)
    return m.group(1) if m else None


def parse_logcat(text: str, package: str) -> tuple[list[HarnessCrash], list[str]]:
    lines = text.splitlines()
    pids = _app_pids(lines, package)
    crashes: list[HarnessCrash] = []
    network: list[str] = []

    def block(i: int, n: int) -> str:
        pid = _line_pid(lines[i])
        out = [lines[i]]
        for ln in lines[i + 1 : i + 1 + n]:
            if pid is not None and _line_pid(ln) not in (pid, None):
                continue
            out.append(ln)
        return "\n".join(out)[:2000]

    for i, ln in enumerate(lines):
        if "FATAL EXCEPTION" in ln:
            b = block(i, 14)
            if package in b or (_line_pid(ln) in pids):
                crashes.append(HarnessCrash(type="crash", excerpt=b))
        elif f"ANR in {package}" in ln:
            crashes.append(HarnessCrash(type="anr", excerpt=block(i, 8)))
        elif "Fatal signal" in ln and (package in ln or _line_pid(ln) in pids):
            crashes.append(HarnessCrash(type="native_crash", excerpt=block(i, 6)))
        elif any(e in ln for e in NETWORK_ERRORS) and (not pids or _line_pid(ln) in pids or package in ln):
            msg = ln.strip()[:240]
            if msg not in network and len(network) < 20:
                network.append(msg)
    return crashes, network
