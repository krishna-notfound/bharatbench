import pytest

from app.analyzer.rules_performance import (
    check_apk_size,
    check_min_sdk_high,
    check_multidex,
    check_native_abis,
    check_no_shrinking,
    check_old_target_sdk,
    performance_findings,
)

MB = 1024 * 1024


@pytest.mark.parametrize("mb,sev", [(120, "high"), (60, "medium"), (30, "low")])
def test_apk_size_positive(make_facts, run_id, mb, sev):
    (f,) = check_apk_size(make_facts(size_bytes=mb * MB), run_id)
    assert f.severity == sev and f.category == "performance" and f.source == "static"


@pytest.mark.parametrize("mb", [5, 25, 25.0])
def test_apk_size_negative(make_facts, run_id, mb):
    assert check_apk_size(make_facts(size_bytes=int(mb * MB)), run_id) == []


def test_native_abis(make_facts, run_id):
    (f,) = check_native_abis(make_facts(native_abis=["arm64-v8a", "armeabi-v7a", "x86"]), run_id)
    assert f.severity == "medium"
    assert check_native_abis(make_facts(native_abis=["arm64-v8a", "x86_64"]), run_id) == []


def test_multidex(make_facts, run_id):
    (f,) = check_multidex(make_facts(dex_count=4), run_id)
    assert f.severity == "low"
    assert check_multidex(make_facts(dex_count=3), run_id) == []


def test_no_shrinking_positive(make_facts, run_id):
    names = [f"Lcom/example/app/Class{i};" for i in range(100)]
    (f,) = check_no_shrinking(make_facts(class_names_sample=names), run_id)
    assert f.severity == "medium"


def test_no_shrinking_negative(make_facts, run_id):
    names = [f"Lcom/example/app/Class{i};" for i in range(90)] + [f"La/b/{c};" for c in "abcdefghij"]
    assert check_no_shrinking(make_facts(class_names_sample=names), run_id) == []
    assert check_no_shrinking(make_facts(class_names_sample=[]), run_id) == []


def test_old_target_sdk(make_facts, run_id):
    (f,) = check_old_target_sdk(make_facts(target_sdk=30), run_id)
    assert f.severity == "medium"
    assert check_old_target_sdk(make_facts(target_sdk=33), run_id) == []


def test_min_sdk_high(make_facts, run_id):
    (f,) = check_min_sdk_high(make_facts(min_sdk=29), run_id)
    assert f.severity == "low"
    assert check_min_sdk_high(make_facts(min_sdk=28), run_id) == []


def test_clean_facts_no_findings(make_facts, run_id):
    names = [f"La/b/{c};" for c in "abcdefghij"]
    assert performance_findings(make_facts(class_names_sample=names), run_id) == []
