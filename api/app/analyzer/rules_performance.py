"""Static performance rules: pure functions (ApkFacts, run_id) -> list[Finding]."""

import re

from app.analyzer.apk import ApkFacts
from app.analyzer.ids import finding_id
from app.models import Evidence, Finding, Severity

_MB = 1024 * 1024
_OBFUSCATED = re.compile(r"^[a-zA-Z]{1,2}$")


def _finding(
    run_id: str,
    rule_id: str,
    title: str,
    severity: Severity,
    description: str,
    evidence: Evidence,
    cause: str,
    fix: str,
) -> Finding:
    return Finding(
        id=finding_id(run_id, rule_id, 1),
        run_id=run_id,
        source="static",
        category="performance",
        rule_id=rule_id,
        title=title,
        severity=severity,
        description=description,
        evidence=[evidence],
        profile_id=None,
        journey_step=None,
        probable_cause=cause,
        suggested_fix=fix,
    )


def check_apk_size(facts: ApkFacts, run_id: str) -> list[Finding]:
    mb = facts.size_bytes / _MB
    if mb > 100:
        severity: Severity = "high"
    elif mb > 50:
        severity = "medium"
    elif mb > 25:
        severity = "low"
    else:
        return []
    return [
        _finding(
            run_id,
            "perf.apk_size",
            f"Large APK ({mb:.0f} MB)",
            severity,
            "Large downloads are costly on limited data plans and storage common among Indian users.",
            Evidence(kind="metric", excerpt=f"size={mb:.1f} MB"),
            "Bundled assets, native libraries or unshrunk code.",
            "Ship an Android App Bundle, compress assets, enable R8 and resource shrinking.",
        )
    ]


def check_native_abis(facts: ApkFacts, run_id: str) -> list[Finding]:
    if len(facts.native_abis) <= 2:
        return []
    return [
        _finding(
            run_id,
            "perf.native_abis",
            f"{len(facts.native_abis)} native ABIs bundled",
            "medium",
            "One APK carries native libraries for several CPU architectures, inflating download size.",
            Evidence(kind="metric", excerpt=", ".join(facts.native_abis)),
            "Universal APK distribution.",
            "Publish as an App Bundle so each device downloads only its ABI.",
        )
    ]


def check_multidex(facts: ApkFacts, run_id: str) -> list[Finding]:
    if facts.dex_count <= 3:
        return []
    return [
        _finding(
            run_id,
            "perf.multidex",
            f"{facts.dex_count} dex files",
            "low",
            "Many dex files slow cold start on low-end devices.",
            Evidence(kind="metric", excerpt=f"dex_count={facts.dex_count}"),
            "Large code base or unused dependencies.",
            "Remove unused libraries and enable R8 shrinking.",
        )
    ]


def _looks_obfuscated(class_name: str) -> bool:
    segments = [s for s in re.split(r"[./$]", class_name.removeprefix("L").removesuffix(";")) if s]
    return bool(segments) and _OBFUSCATED.match(segments[-1]) is not None


def check_no_shrinking(facts: ApkFacts, run_id: str) -> list[Finding]:
    names = facts.class_names_sample
    if not names:
        return []
    ratio = sum(_looks_obfuscated(n) for n in names) / len(names)
    if ratio >= 0.05:
        return []
    return [
        _finding(
            run_id,
            "perf.no_shrinking",
            "Code shrinking/obfuscation appears disabled",
            "medium",
            "Almost no class names look minified, so R8 is probably off and the app is larger and slower.",
            Evidence(kind="metric", excerpt=f"obfuscated class names: {ratio:.1%} of {len(names)} sampled"),
            "minifyEnabled is false in the release build.",
            "Enable minifyEnabled and shrinkResources for release builds.",
        )
    ]


def check_old_target_sdk(facts: ApkFacts, run_id: str) -> list[Finding]:
    if facts.target_sdk is None or facts.target_sdk >= 33:
        return []
    return [
        _finding(
            run_id,
            "perf.old_target_sdk",
            f"Old targetSdkVersion ({facts.target_sdk})",
            "medium",
            "Targeting an old SDK misses platform performance and battery behaviour and can block updates.",
            Evidence(kind="manifest", excerpt=f"targetSdkVersion={facts.target_sdk}"),
            "targetSdk not updated.",
            "Raise targetSdkVersion to the current level and test.",
        )
    ]


def check_min_sdk_high(facts: ApkFacts, run_id: str) -> list[Finding]:
    if facts.min_sdk is None or facts.min_sdk <= 28:
        return []
    return [
        _finding(
            run_id,
            "perf.min_sdk_high",
            f"High minSdkVersion ({facts.min_sdk})",
            "low",
            "Older budget phones common in India cannot install this app.",
            Evidence(kind="manifest", excerpt=f"minSdkVersion={facts.min_sdk}"),
            "minSdk set above Android 9.",
            "Lower minSdkVersion if the app can support older devices.",
        )
    ]


RULES = [
    check_apk_size,
    check_native_abis,
    check_multidex,
    check_no_shrinking,
    check_old_target_sdk,
    check_min_sdk_high,
]


def performance_findings(facts: ApkFacts, run_id: str) -> list[Finding]:
    return [f for rule in RULES for f in rule(facts, run_id)]
