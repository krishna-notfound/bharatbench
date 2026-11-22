from harness.forms import fillable_fields, is_login_gate
from harness.parsers import parse_ui_nodes


def _xml(*nodes: str) -> str:
    return "<hierarchy>" + "".join(nodes) + "</hierarchy>"


def _edit(rid: str, hint: str = "", password: bool = False, y: int = 0) -> str:
    return (
        f'<node class="android.widget.EditText" resource-id="{rid}" text="" hint="{hint}" content-desc="" '
        f'clickable="true" focusable="true" password="{str(password).lower()}" enabled="true" '
        f'bounds="[0,{y}][500,{y + 80}]" />'
    )


def _text(t: str, y: int = 900) -> str:
    return f'<node class="android.widget.TextView" text="{t}" resource-id="" content-desc="" bounds="[0,{y}][500,{y + 40}]" />'


def _gate(xml: str) -> bool:
    nodes = parse_ui_nodes(xml)
    return is_login_gate(nodes, fillable_fields(nodes, set()))


def test_password_screen_is_a_gate():
    assert _gate(_xml(_edit("id/email", "Email"), _edit("id/pwd", "Password", password=True, y=100)))


def test_email_on_sign_in_screen_is_a_gate():
    assert _gate(_xml(_text("Sign in to continue"), _edit("id/email", "Email")))


def test_otp_screen_is_a_gate():
    assert _gate(_xml(_text("Enter the OTP sent to your phone"), _edit("id/otp", "OTP")))


def test_newsletter_or_contact_email_is_not_a_gate():
    assert not _gate(_xml(_text("Subscribe to our newsletter"), _edit("id/email", "Email")))


def test_search_box_is_not_a_gate():
    assert not _gate(_xml(_edit("id/search", "Search products")))


def test_signup_profile_form_without_password_is_not_a_gate():
    assert not _gate(_xml(_text("Your details"), _edit("id/name", "Full name"), _edit("id/phone", "Mobile number", y=100)))
