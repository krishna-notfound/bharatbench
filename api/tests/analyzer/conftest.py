import pytest

from app.analyzer.apk import ApkFacts

RUN = "abcdef123456"


@pytest.fixture
def run_id() -> str:
    return RUN


@pytest.fixture
def make_facts():
    def _make(**kw) -> ApkFacts:
        base = {
            "package": "com.example.app",
            "target_sdk": 34,
            "min_sdk": 24,
            "size_bytes": 10 * 1024 * 1024,
            "app_attrs": {"allowBackup": "false"},
            "main_activity": "com.example.app.Main",
        }
        base.update(kw)
        return ApkFacts(**base)

    return _make
