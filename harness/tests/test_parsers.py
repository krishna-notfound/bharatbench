from harness.parsers import (
    clickable_nodes,
    has_progress,
    is_denied,
    normalize_activity,
    parse_df_free_kb,
    parse_launch_time,
    parse_logcat,
    parse_meminfo_pss,
    parse_resolve_activity,
    parse_resumed_activity,
    parse_ui_nodes,
)

PKG = "com.example.shop"


def test_logcat_crash_anr_native_filtered_to_app(fixtures):
    crashes, net = parse_logcat((fixtures / "logcat.txt").read_text(), PKG)
    kinds = [c.type for c in crashes]
    assert kinds == ["crash", "anr", "native_crash"]  # other app's FATAL EXCEPTION excluded
    assert "NullPointerException" in crashes[0].excerpt
    assert "Input dispatching timed out" in crashes[1].excerpt
    assert any("SocketTimeoutException" in n for n in net)
    assert any("UnknownHostException" in n for n in net)
    assert any("unexpected end of stream" in n for n in net)
    assert not any("other app noise" in n for n in net)  # other pid filtered


def test_logcat_empty():
    assert parse_logcat("", PKG) == ([], [])


def test_ui_nodes_and_denylist(fixtures):
    nodes = parse_ui_nodes((fixtures / "ui_list.xml").read_text())
    click = clickable_nodes(nodes)
    assert [n.label for n in click] == ["Log out", "Products", "Cart"]
    assert [is_denied(n) for n in click] == [True, False, False]
    assert click[1].center == (300, 250)
    assert not has_progress(nodes)


def test_ui_progress_and_garbage(fixtures):
    assert has_progress(parse_ui_nodes((fixtures / "ui_loading.xml").read_text()))
    assert parse_ui_nodes("ERROR: null root node") == []
    assert parse_ui_nodes("<hierarchy><unclosed>") == []


def test_launch_time(fixtures):
    assert parse_launch_time((fixtures / "am_start.txt").read_text()) == 1234
    assert parse_launch_time("Error type 3\nError: Activity class does not exist.") is None


def test_meminfo_and_df(fixtures):
    assert parse_meminfo_pss((fixtures / "meminfo.txt").read_text()) == 98765
    assert parse_meminfo_pss("TOTAL   4321   100") == 4321
    assert parse_df_free_kb((fixtures / "df.txt").read_text()) == 4900000
    assert parse_df_free_kb("garbage") is None


def test_activities(fixtures):
    fg = parse_resumed_activity((fixtures / "resumed.txt").read_text())
    assert fg == "com.example.shop/.MainActivity"
    assert normalize_activity(fg, PKG) == "com.example.shop/com.example.shop.MainActivity"
    assert parse_resolve_activity("priority=0 ...\n  com.example.shop/.MainActivity\n") == "com.example.shop/.MainActivity"
    assert parse_resumed_activity("") is None
