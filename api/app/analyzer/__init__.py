"""Analyzer: static APK scan + runtime evidence rules."""

from pathlib import Path

from app.analyzer.apk import load_apk_facts
from app.analyzer.maestro import steps_to_maestro
from app.analyzer.rules_performance import performance_findings
from app.analyzer.rules_runtime import runtime_findings
from app.analyzer.rules_security import security_findings
from app.models import AppInfo, Finding

__all__ = ["analyze_apk", "runtime_findings", "steps_to_maestro"]


def analyze_apk(apk_path: Path, run_id: str) -> tuple[AppInfo, list[Finding]]:
    """Synchronous static scan; callers run it via asyncio.to_thread. Raises ValueError on a bad APK."""
    facts = load_apk_facts(Path(apk_path))
    info = AppInfo(
        package_name=facts.package,
        app_name=facts.app_name,
        version_name=facts.version_name,
        version_code=facts.version_code,
        min_sdk=facts.min_sdk,
        target_sdk=facts.target_sdk,
        size_bytes=facts.size_bytes,
        permissions=facts.permissions,
        main_activity=facts.main_activity,
        native_abis=facts.native_abis,
        dex_count=facts.dex_count,
    )
    return info, security_findings(facts, run_id) + performance_findings(facts, run_id)
