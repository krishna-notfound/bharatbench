"""APK loading: androguard (4.x) -> ApkFacts. The only module that touches androguard."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from lxml import etree

logger.disable("androguard")  # androguard logs via loguru at INFO/DEBUG; keep the API log clean

ANDROID_NS = "http://schemas.android.com/apk/res/android"
MAX_STRINGS = 200_000
MAX_STRING_LEN = 2048
CLASS_SAMPLE = 2000
_COMPONENT_TAGS = ("activity", "activity-alias", "service", "receiver", "provider")


@dataclass
class Component:
    kind: str  # activity | service | receiver | provider
    name: str
    exported: bool | None = None
    permission: str | None = None
    has_intent_filter: bool = False
    launcher: bool = False  # MAIN/LAUNCHER entry point (must be exported)
    deep_link: bool = False  # VIEW + BROWSABLE (must be exported to receive links)


@dataclass
class ApkFacts:
    manifest_xml: str = ""
    package: str = ""
    app_name: str | None = None
    version_name: str | None = None
    version_code: str | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None
    size_bytes: int = 0
    permissions: list[str] = field(default_factory=list)
    main_activity: str | None = None
    components: list[Component] = field(default_factory=list)
    app_attrs: dict[str, str] = field(default_factory=dict)
    network_security_config: str | None = None
    strings: list[str] = field(default_factory=list)
    native_abis: list[str] = field(default_factory=list)
    dex_count: int = 0
    class_names_sample: list[str] = field(default_factory=list)
    uses_webview_js: bool = False


def _attr(el: etree._Element, name: str) -> str | None:
    value = el.get(f"{{{ANDROID_NS}}}{name}")
    if value is None:
        return None
    if value in ("-1", "0xffffffff", "0xFFFFFFFF"):
        return "true"
    if value in ("0", "0x0"):
        return "false"
    return value


def _bool(value: str | None) -> bool | None:
    return None if value is None else value.lower() == "true"


def _to_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _qualify(package: str, name: str) -> str:
    if name.startswith("."):
        return package + name
    return name if "." in name else f"{package}.{name}"


def _components(manifest: etree._Element, package: str) -> list[Component]:
    app = manifest.find("application")
    if app is None:
        return []
    out: list[Component] = []
    for kind in _COMPONENT_TAGS:
        for el in app.findall(kind):
            name = _attr(el, "name")
            if not name:
                continue
            filters = el.findall("intent-filter")
            has_filter = bool(filters)
            actions = {_attr(a, "name") for f in filters for a in f.findall("action")}
            cats = {_attr(c, "name") for f in filters for c in f.findall("category")}
            launcher = "android.intent.category.LAUNCHER" in cats or (
                "android.intent.action.MAIN" in actions and "android.intent.category.INFO" in cats
            )
            deep_link = "android.intent.action.VIEW" in actions and "android.intent.category.BROWSABLE" in cats
            exported = _bool(_attr(el, "exported"))
            if exported is None and (has_filter and kind != "provider"):
                exported = True  # implicit export for filtered components (pre-Android 12 default)
            out.append(
                Component(
                    kind="activity" if kind == "activity-alias" else kind,
                    name=_qualify(package, name),
                    exported=exported,
                    permission=_attr(el, "permission"),
                    has_intent_filter=has_filter,
                    launcher=launcher,
                    deep_link=deep_link,
                )
            )
    return out


def _dex_facts(apk: object) -> tuple[list[str], list[str], int]:
    from androguard.core.dex import DEX

    strings: list[str] = []
    classes: list[str] = []
    dex_blobs = list(apk.get_all_dex())  # type: ignore[attr-defined]
    for blob in dex_blobs:
        dex = DEX(blob)
        for s in dex.get_strings():
            if len(strings) >= MAX_STRINGS:
                break
            text = str(s).replace("\0", "")
            if len(text) <= MAX_STRING_LEN:
                strings.append(text)
        classes.extend(dex.get_classes_names())
    step = max(1, len(classes) // CLASS_SAMPLE)
    return strings, classes[::step][:CLASS_SAMPLE], len(dex_blobs)


MAX_ENTRIES = 20_000
MAX_UNCOMPRESSED = 1536 * 1024 * 1024  # 1.5 GiB of declared content for a <=200 MB upload
MAX_RATIO = 200


def _check_zip_budget(apk_path: Path) -> None:
    """Refuse zip bombs before androguard inflates anything (central directory only; nothing is extracted)."""
    import zipfile

    try:
        with zipfile.ZipFile(apk_path) as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"Not a valid APK: {exc}") from exc
    total = sum(i.file_size for i in infos)
    packed = max(sum(i.compress_size for i in infos), 1)
    if len(infos) > MAX_ENTRIES or total > MAX_UNCOMPRESSED or total / packed > MAX_RATIO:
        raise ValueError("Not a valid APK: archive is too large when unpacked")


def load_apk_facts(apk_path: Path) -> ApkFacts:
    """Parse an APK into ApkFacts. Raises ValueError("Not a valid APK: ...") on broken input."""
    from androguard.core.apk import APK

    _check_zip_budget(apk_path)
    try:
        apk = APK(str(apk_path))
        if not apk.is_valid_APK():
            raise ValueError("missing AndroidManifest.xml")
        manifest = apk.get_android_manifest_xml()
        if manifest is None:
            raise ValueError("unreadable AndroidManifest.xml")
        strings, class_sample, dex_count = _dex_facts(apk)
    except ValueError as exc:
        raise ValueError(f"Not a valid APK: {exc}") from exc
    except Exception as exc:  # androguard raises assorted parser/zip errors on corrupt input
        raise ValueError(f"Not a valid APK: {exc}") from exc

    package = apk.get_package() or ""
    app_el = manifest.find("application")
    app_attrs: dict[str, str] = {}
    if app_el is not None:
        for key, value in app_el.attrib.items():
            local = key.split("}", 1)[-1]
            app_attrs[local] = _attr(app_el, local) or value
    abis = sorted({p.split("/")[1] for p in apk.get_files() if p.startswith("lib/") and p.count("/") >= 2})

    return ApkFacts(
        manifest_xml=etree.tostring(manifest, pretty_print=True).decode("utf-8", "replace"),
        package=package,
        app_name=apk.get_app_name() or None,
        version_name=apk.get_androidversion_name(),
        version_code=apk.get_androidversion_code(),
        min_sdk=_to_int(apk.get_min_sdk_version()),
        target_sdk=_to_int(apk.get_target_sdk_version()),
        size_bytes=apk_path.stat().st_size,
        permissions=list(apk.get_permissions()),
        main_activity=apk.get_main_activity(),
        components=_components(manifest, package),
        app_attrs=app_attrs,
        network_security_config=app_attrs.get("networkSecurityConfig"),
        strings=strings,
        native_abis=abis,
        dex_count=dex_count,
        class_names_sample=class_sample,
        uses_webview_js="addJavascriptInterface" in strings,
    )
