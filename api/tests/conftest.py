import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import pipeline
from app.models import AppInfo, Evidence, Finding, HarnessResult, Run
from app.settings import Settings


def make_apk_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("AndroidManifest.xml", "x")
    return buf.getvalue()


def make_finding(fid: str = "f1", run_id: str = "r", **kw: object) -> Finding:
    base: dict[str, object] = {
        "id": fid,
        "run_id": run_id,
        "source": "static",
        "category": "security",
        "rule_id": "sec.test",
        "title": f"Finding {fid}",
        "severity": "medium",
        "description": "desc",
        "evidence": [Evidence(kind="note", excerpt="x")],
    }
    base.update(kw)
    return Finding(**base)  # type: ignore[arg-type]


def make_run(run_id: str = "r1", status: str = "queued") -> Run:
    now = datetime.now(UTC)
    return Run(
        id=run_id, apk_name="a.apk", status=status, profile_ids=["baseline"], created_at=now, updated_at=now  # type: ignore[arg-type]
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data")  # type: ignore[call-arg]


@pytest.fixture
def fake_analyzer(monkeypatch: pytest.MonkeyPatch):
    """Replace the f03 analyzer with deterministic fakes."""

    def analyze_apk(apk_path: Path, run_id: str):
        info = AppInfo(package_name="com.example.app", main_activity=".Main", size_bytes=10)
        return info, [
            make_finding("s1", run_id, severity="low", rule_id="sec.low"),
            make_finding("s2", run_id, severity="critical", rule_id="sec.crit"),
        ]

    def runtime_findings(run_id: str, result: HarnessResult, package: str = "pkg"):
        return [
            make_finding(
                "rt1", run_id, source="runtime", category="reliability", severity="high",
                rule_id="rt.crash", profile_id="budget_2gb", journey_step=0,
            )
        ]

    monkeypatch.setattr(pipeline, "load_analyzer", lambda: (analyze_apk, runtime_findings))
    return analyze_apk, runtime_findings
