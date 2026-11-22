import pytest

from harness.adb import Adb
from harness.crawler import Crawler
from harness.forms import adb_text, fillable_fields, infer_field_kind, is_submit
from harness.parsers import UiNode, parse_ui_nodes

from .device import PKG, FakeDevice, make_xml
from .test_crawler import Clock


def node(rid="", hint="", text="", desc="", password=False, y=100):
    return UiNode("android.widget.EditText", text, desc, rid, (0, y, 500, y + 50), True, password, hint)


@pytest.mark.parametrize(
    ("kw", "kind"),
    [
        ({"rid": "com.x:id/et_email"}, "email"),
        ({"hint": "Enter your e-mail"}, "email"),
        ({"rid": "mobile_number"}, "phone"),
        ({"hint": "Phone"}, "phone"),
        ({"hint": "Enter OTP"}, "otp"),
        ({"desc": "Verification code"}, "otp"),
        ({"hint": "Enter 4 digit PIN"}, "pin"),
        ({"hint": "Pincode"}, "pincode"),
        ({"hint": "Zip"}, "pincode"),
        ({"password": True}, "password"),
        ({"hint": "Password"}, "password"),
        ({"rid": "input_full_name"}, "name"),
        ({"hint": "City"}, "city"),
        ({"hint": "Street address"}, "address"),
        ({"hint": "Amount in INR"}, "amount"),
        ({"rid": "search_src_text"}, "search"),
        ({"hint": "Date of birth"}, "date"),
        ({"hint": "Anything"}, "text"),
        ({"text": "Mobile", "hint": "Mobile"}, "phone"),  # placeholder reported as text
    ],
)
def test_field_kind_inference(kw, kind):
    assert infer_field_kind(node(**kw)) == kind


def test_kind_from_nearby_label():
    nodes = parse_ui_nodes(make_xml(["Email address"], fields=[{}]))
    field = next(n for n in nodes if n.editable)
    assert infer_field_kind(field, nodes) == "email"


def test_fillable_skips_filled_and_done():
    nodes = [node(hint="Email"), node(text="already here", y=200), node(hint="City", y=300)]
    fields = fillable_fields(nodes, set())
    assert [f.kind for f in fields] == ["email", "city"]
    assert [f.kind for f in fillable_fields(nodes, {fields[0].key})] == ["city"]


def test_adb_text_escapes_spaces():
    assert adb_text("Asha Verma") == "Asha%sVerma"


def test_submit_detection_and_denylist():
    def btn(t):
        return UiNode("android.widget.Button", t, "", "", (0, 0, 10, 10), True)

    assert all(is_submit(btn(t)) for t in ["Continue", "Sign in", "Log in", "Get OTP", "Search", "Save", "Verify"])
    assert not any(is_submit(btn(t)) for t in ["Pay now", "Buy", "Delete", "Log out", "Call", "Home"])


def make(dev, tmp_path, sleep=None):
    clock = Clock()
    return Crawler(
        Adb("adb", "emulator-5554", dev), PKG, ".MainActivity", tmp_path, "baseline",
        sleep=sleep or clock.sleep, clock=clock.now,
    )  # fmt: skip


async def test_form_filled_once_then_submitted_keyboard_hidden_secret_masked(tmp_path):
    form = make_xml(["Welcome"], ["Continue"], fields=[{"hint": "Email"}, {"hint": "Password", "password": True}])
    dev = FakeDevice([form, make_xml(["Next screen"])])
    j = await make(dev, tmp_path).run(2)
    fills = [s for s in j.steps if s.action == "fill"]
    assert [s.target for s in fills] == ["email", "password"]
    assert dev.typed == ["asha.verma@example.com", "Test@12345"]
    assert all("Test@12345" not in (s.note or "") + (s.target or "") for s in j.steps)
    assert "masked" in fills[1].note and "masked" not in fills[0].note
    assert any(c[-1] == "KEYCODE_BACK" for c in dev.calls)  # keyboard was shown -> hidden
    assert dev.keyboard is False
    assert [s.action for s in j.steps][:4] == ["launch", "fill", "fill", "tap"]
    assert j.steps[3].target == "Continue"


async def test_no_back_when_keyboard_not_shown(tmp_path):
    dev = FakeDevice([make_xml(["Hi"], ["Search"], fields=[{"hint": "Search"}]), make_xml(["Results"])])
    dev.keyboard_on_type = False
    await make(dev, tmp_path).run(1)
    assert dev.typed == ["test"]
    assert not any(c[-1] == "KEYCODE_BACK" for c in dev.calls)


async def test_denied_submit_is_not_tapped(tmp_path):
    dev = FakeDevice([make_xml(["Cart"], ["Pay now"], fields=[{"hint": "Amount"}]), make_xml(["x"])])
    j = await make(dev, tmp_path).run(1)
    assert [s.target for s in j.steps if s.action == "fill"] == ["amount"]
    assert dev.typed == ["100"]
    assert not any(s.target == "Pay now" for s in j.steps)


async def test_fields_not_refilled_on_next_iteration(tmp_path):
    dev = FakeDevice([make_xml(["Hi"], [], fields=[{"hint": "Email"}])])
    await make(dev, tmp_path).run(3)
    assert dev.typed == ["asha.verma@example.com"]


async def test_settle_uses_change_detection_not_fixed_sleeps(tmp_path):
    dev = FakeDevice([make_xml(["A"], ["Go"]), make_xml(["B"], ["Next"]), make_xml(["C"])])
    sleeps: list[float] = []
    clock = Clock()

    async def sleep(s):
        sleeps.append(s)
        await clock.sleep(s)

    c = Crawler(Adb("adb", "emulator-5554", dev), PKG, ".MainActivity", tmp_path, "baseline", sleep=sleep, clock=clock.now)
    j = await c.run(2)
    assert j.launched and len(j.screens) == 3
    assert sleeps and max(sleeps) <= 0.5  # only short polls; no 1 s / 3 s fixed waits


async def test_unchanged_screen_reuses_screenshot_and_foreground(tmp_path):
    dev = FakeDevice([make_xml(["Only"])])
    j = await make(dev, tmp_path).run(3)
    assert len(j.screens) == 4
    assert len({s.screenshot for s in j.screens}) == 1
    assert sum("screencap" in " ".join(c) for c in dev.calls) == 1
    assert sum("ResumedActivity" in " ".join(c) for c in dev.calls) <= 3  # launch wait + first capture
