import os
import tempfile
import zipfile
from pathlib import Path

import pytest

from app.analyzer import analyze_apk
from app.models import AppInfo, Finding

SAMPLE = os.environ.get("BB_SAMPLE_APK")


def test_not_an_apk_raises():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "bad.apk"
        bad.write_bytes(b"this is not a zip")
        with pytest.raises(ValueError, match="Not a valid APK"):
            analyze_apk(bad, "run12345")


def test_zip_without_manifest_raises():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "empty.apk"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("hello.txt", "x")
        with pytest.raises(ValueError, match="Not a valid APK"):
            analyze_apk(bad, "run12345")


@pytest.mark.skipif(not SAMPLE or not Path(SAMPLE).exists(), reason="BB_SAMPLE_APK not set")
def test_real_apk():
    info, findings = analyze_apk(Path(SAMPLE), "run12345")
    assert isinstance(info, AppInfo) and info.package_name and info.size_bytes > 0
    assert info.dex_count >= 1 and info.permissions
    assert all(isinstance(f, Finding) and f.source == "static" and f.evidence for f in findings)
    print(info.package_name, [(f.rule_id, f.severity) for f in findings])
