"""Minimal Android binary-manifest (AXML) reader: lists exported components. Stdlib only, no I/O beyond the zip."""

import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

_TYPE_STRING, _TYPE_BOOL = 0x03, 0x12
_KINDS = {"activity": "activity", "activity-alias": "activity", "service": "service", "receiver": "receiver"}
_LAUNCHER = "android.intent.category.LAUNCHER"


@dataclass(frozen=True)
class Component:
    kind: str  # activity | service | receiver
    name: str  # fully qualified class name
    exported: bool
    has_filter: bool
    launcher: bool
    permission: str | None


def _read_pool(data: bytes, off: int) -> list[str]:
    _, hdr, _size, count, _styles, flags, str_start, _style_start = struct.unpack_from("<HHIIIIII", data, off)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f"<{count}I", data, off + hdr)
    base = off + str_start
    out: list[str] = []
    for o in offsets:
        p = base + o
        if utf8:
            p += 2 if data[p] & 0x80 else 1  # skip the utf-16 char length
            ln = data[p]
            p += 1
            if ln & 0x80:
                ln = ((ln & 0x7F) << 8) | data[p]
                p += 1
            out.append(data[p : p + ln].decode("utf-8", "replace"))
        else:
            ln = struct.unpack_from("<H", data, p)[0]
            p += 2
            if ln & 0x8000:
                ln = ((ln & 0x7FFF) << 16) | struct.unpack_from("<H", data, p)[0]
                p += 2
            out.append(data[p : p + ln * 2].decode("utf-16-le", "replace"))
    return out


Event = tuple[str, dict[str, "str | bool"], bool]


def _events(data: bytes) -> list[Event]:
    """Flat element events (tag, attrs, is_start). Attribute keys are bare names."""
    strings: list[str] = []
    events: list[Event] = []
    off = struct.unpack_from("<H", data, 2)[0]
    while off + 8 <= len(data):
        ctype, _hdr, size = struct.unpack_from("<HHI", data, off)
        if size == 0:
            break
        if ctype == 0x0001:
            strings = _read_pool(data, off)
        elif ctype == 0x0102:
            name_i = struct.unpack_from("<I", data, off + 20)[0]
            attr_start, attr_size, attr_count = struct.unpack_from("<HHH", data, off + 24)
            attrs: dict[str, str | bool] = {}
            for i in range(attr_count):
                a = off + 16 + attr_start + i * attr_size
                _ns, nm, raw, _sz, _r0, vtype, vdata = struct.unpack_from("<iiiHBBI", data, a)
                key = strings[nm] if 0 <= nm < len(strings) else ""
                if vtype == _TYPE_BOOL:
                    attrs[key] = vdata != 0
                elif vtype == _TYPE_STRING and vdata < len(strings):
                    attrs[key] = strings[vdata]
                elif 0 <= raw < len(strings):
                    attrs[key] = strings[raw]
            events.append((strings[name_i], attrs, True))
        elif ctype == 0x0103:
            events.append((strings[struct.unpack_from("<I", data, off + 20)[0]], {}, False))
        off += size
    return events


def _qualify(name: str, pkg: str | None) -> str:
    if name.startswith("."):
        return (pkg or "") + name
    if "." not in name and pkg:
        return f"{pkg}.{name}"
    return name


def parse_components(apk: Path) -> tuple[str | None, list[Component]]:
    """(manifest package, components exported per manifest rules). Raises on an unreadable APK."""
    with zipfile.ZipFile(apk) as z:
        data = z.read("AndroidManifest.xml")
    pkg: str | None = None
    comps: list[Component] = []
    cur: dict[str, object] | None = None
    for tag, attrs, start in _events(data):
        if start and tag == "manifest":
            p = attrs.get("package")
            pkg = p if isinstance(p, str) else None
        elif start and tag in _KINDS:
            n = attrs.get("name")
            cur = (
                {"kind": _KINDS[tag], "name": n, "exp": attrs.get("exported"), "filter": False,
                 "launcher": False, "perm": attrs.get("permission")}
                if isinstance(n, str)
                else None
            )
        elif start and tag == "intent-filter" and cur is not None:
            cur["filter"] = True
        elif start and tag == "category" and cur is not None and attrs.get("name") == _LAUNCHER:
            cur["launcher"] = True
        elif not start and tag in _KINDS and cur is not None:
            exp = cur["exp"]
            exported = exp if isinstance(exp, bool) else bool(cur["filter"])  # no attr: exported iff it has a filter
            perm = cur["perm"]
            comps.append(
                Component(
                    str(cur["kind"]), _qualify(str(cur["name"]), pkg), exported, bool(cur["filter"]),
                    bool(cur["launcher"]), perm if isinstance(perm, str) else None,
                )
            )
            cur = None
    return pkg, [c for c in comps if c.exported]
