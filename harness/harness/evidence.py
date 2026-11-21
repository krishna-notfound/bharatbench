"""Per-profile evidence: logcat dump + parsed crashes/network errors, and memory PSS."""

from dataclasses import dataclass, field
from pathlib import Path

from .adb import Adb
from .models import HarnessCrash, ProfileId
from .parsers import parse_logcat, parse_meminfo_pss


@dataclass
class Evidence:
    logcat: str | None = None
    crashes: list[HarnessCrash] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    memory_pss_kb: int | None = None


async def collect(adb: Adb, package: str, profile_id: ProfileId, job_dir: Path) -> Evidence:
    ev = Evidence()
    rc, out, _ = await adb.run(["logcat", "-d", "-v", "threadtime"], timeout=60)
    if rc == 0:
        (job_dir / "logcat").mkdir(parents=True, exist_ok=True)
        rel = f"logcat/{profile_id}.txt"
        (job_dir / rel).write_text(out, encoding="utf-8")
        ev.logcat = rel
        ev.crashes, ev.network_errors = parse_logcat(out, package)
    rc, out, _ = await adb.shell("dumpsys", "meminfo", package, timeout=30)
    if rc == 0:
        ev.memory_pss_kb = parse_meminfo_pss(out)
    return ev
