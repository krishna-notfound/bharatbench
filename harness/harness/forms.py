"""Form-field inference for the crawler: which editable field is it, what to type, which button submits. No I/O."""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .parsers import UiNode, is_denied

if TYPE_CHECKING:
    from .secrets import Secrets

# kind -> value typed into the field (deterministic test data, never real).
FIELD_VALUES: dict[str, str] = {
    "email": "asha.verma@example.com",
    "phone": "9876543210",
    "otp": "123456",
    "pin": "1234",
    "password": "Test@12345",
    "username": "asha_verma",
    "name": "Asha Verma",
    "pincode": "560001",
    "city": "Bengaluru",
    "address": "12 MG Road",
    "amount": "100",
    "search": "test",
    "date": "01/01/1995",
    "text": "test",
}
SECRET_KINDS = frozenset({"password", "pin", "otp"})
# Kinds only the user can supply (f24): the crawler asks for these live unless a test account already covers them.
ASK_LABELS: dict[str, str] = {
    "username": "Username or login ID",
    "email": "Email",
    "phone": "Phone number",
    "password": "Password",
    "otp": "One-time code (OTP)",
    "pin": "PIN",
}

# Order matters: first match wins.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("password", re.compile(r"pass\s*word|passcode|\bpwd\b", re.IGNORECASE)),
    ("otp", re.compile(r"\botp\b|one.?time|verification\s*code|\bcode\b|\bsms\s*code", re.IGNORECASE)),
    ("pincode", re.compile(r"pin\s*code|pincode|postal|zip", re.IGNORECASE)),
    ("pin", re.compile(r"\bpin\b|\bmpin\b|\bcvv\b", re.IGNORECASE)),
    ("username", re.compile(r"user\s*(name|id)|\blogin\b", re.IGNORECASE)),
    ("email", re.compile(r"e.?mail", re.IGNORECASE)),
    ("phone", re.compile(r"phone|mobile|contact\s*(no|num)|\bmsisdn\b|\btel\b", re.IGNORECASE)),
    ("amount", re.compile(r"amount|\bprice\b|\bsum\b|\bqty\b|quantity|rupee|\binr\b|\bbudget\b", re.IGNORECASE)),
    ("search", re.compile(r"search|\bfind\b|\bquery\b", re.IGNORECASE)),
    ("date", re.compile(r"\bdate\b|\bdob\b|birth|\bdd.?mm|mm.?dd", re.IGNORECASE)),
    ("city", re.compile(r"\bcity\b|\btown\b|district", re.IGNORECASE)),
    ("address", re.compile(r"address|street|locality|landmark", re.IGNORECASE)),
    ("name", re.compile(r"name|\bwho\b", re.IGNORECASE)),
]

_SUBMIT = re.compile(
    r"^\s*(continue|next|sign\s*in|log\s*in|login|submit|verify|get\s*otp|send\s*otp|search|save|done|"
    r"register|sign\s*up|proceed|confirm|go)\s*[.!>→]*\s*$",
    re.IGNORECASE,
)


def _nearby_label(field: UiNode, nodes: list[UiNode]) -> str:
    """Closest non-interactive text just above (or left of) the field."""
    x1, y1, x2, y2 = field.bounds
    best: tuple[int, str] | None = None
    for n in nodes:
        if n is field or n.editable or n.clickable or not n.text.strip():
            continue
        nx1, ny1, nx2, ny2 = n.bounds
        above = 0 <= y1 - ny2 <= 140 and nx1 < x2 and nx2 > x1
        left = abs((ny1 + ny2) // 2 - (y1 + y2) // 2) < 60 and 0 <= x1 - nx2 <= 200
        if above or left:
            dist = (y1 - ny2) if above else (x1 - nx2)
            if best is None or dist < best[0]:
                best = (dist, n.text)
    return best[1] if best else ""


def infer_field_kind(field: UiNode, nodes: list[UiNode] | None = None) -> str:
    if field.password:
        return "password"
    own = f"{field.rid.rsplit('/', 1)[-1].replace('_', ' ')} {field.hint} {field.desc}"
    own_text = field.text if field.text and field.text != field.hint else ""
    for source in (own, own_text, _nearby_label(field, nodes) if nodes else ""):
        for kind, rx in _RULES:
            if source.strip() and rx.search(source):
                return kind
    return "text"


def is_empty(field: UiNode) -> bool:
    """Empty, or showing only its placeholder (older uiautomator reports the hint as text)."""
    return not field.text.strip() or field.text == field.hint


@dataclass(frozen=True)
class FormField:
    node: UiNode
    kind: str

    @property
    def value(self) -> str:
        return FIELD_VALUES[self.kind]

    def real_value(self, secrets: "Secrets | None") -> tuple[str, bool]:
        """(value to type, True when it is a real test-account value that must stay hidden)."""
        if secrets is not None:
            mine = secrets.user_value(self.kind)
            if mine:
                return mine, True
            if self.kind == "password" and secrets.password:
                return secrets.password, True
            if self.kind == "otp" and secrets.otp:
                return secrets.otp, True
            login = secrets.login
            digits = re.sub(r"[\s+()-]", "", login)
            if login and (
                self.kind == "username"
                or (self.kind == "email" and "@" in login)
                or (self.kind == "phone" and digits.isdigit())
            ):
                return login, True
        return self.value, False

    @property
    def key(self) -> str:
        return f"{self.node.rid}{self.node.bounds}"


def fillable_fields(nodes: list[UiNode], done: set[str]) -> list[FormField]:
    out = []
    for n in nodes:
        if not n.editable or not n.enabled or n.bounds[2] <= n.bounds[0] or n.bounds[3] <= n.bounds[1]:
            continue
        f = FormField(n, infer_field_kind(n, nodes))
        if f.key in done or not is_empty(n):
            continue
        out.append(f)
    return out


def adb_text(value: str) -> str:
    """`input text` needs spaces as %s."""
    return value.replace("%", "%25").replace(" ", "%s")


def is_submit(node: UiNode) -> bool:
    if is_denied(node) or not node.clickable:
        return False
    return bool(_SUBMIT.match(node.text) or _SUBMIT.match(node.desc))


def pick_submit(nodes: list[UiNode], tapped: set[str]) -> UiNode | None:
    for n in nodes:
        if is_submit(n) and f"{n.label}{n.bounds}" not in tapped:
            return n
    return None

_GATE_WORDS = re.compile(
    r"\b(log ?in|sign ?in|signin|login|verify|verification|otp|one[- ]time|passcode|password|enter (?:the )?code|"
    r"mpin|pin)\b",
    re.IGNORECASE,
)


def is_login_gate(nodes: list[UiNode], fields: list[FormField]) -> bool:
    """Ask the human only on a real login / OTP screen, never on ordinary forms (signup, search, contact, profile).

    A gate has a secret field (password / OTP / PIN), or an account field (email / phone / username) on a screen whose
    own words say log in / sign in / verify / OTP."""
    kinds = {f.kind for f in fields}
    if kinds & {"password", "otp", "pin"}:
        return True
    if not kinds & {"email", "phone", "username"}:
        return False
    words = " ".join(f"{n.text} {n.desc} {n.rid}" for n in nodes)
    return bool(_GATE_WORDS.search(words))

