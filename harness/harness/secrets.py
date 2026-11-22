"""Optional test account (f23): real values live only in memory for one job.

The LLM only ever sees the tokens <LOGIN>, <PASSWORD>, <OTP>; the real value is substituted at `input text` time.
Anything that could be stored (steps, captions, UI dumps, events) goes through `mask` first.
"""

import re

from .models import TestCredentials

LOGIN, PASSWORD, OTP = "<LOGIN>", "<PASSWORD>", "<OTP>"
_DIGITS = re.compile(r"\d{4,8}")
MIN_MASK_LEN = 3


class Secrets:
    def __init__(self, creds: TestCredentials | None) -> None:
        c = creds or TestCredentials()
        self.login = c.login.strip()
        self.password = c.password
        self.note = c.note.strip()
        m = _DIGITS.search(self.note)
        self.otp = m.group(0) if m else ""
        self.offline_after_login = c.offline_after_login

    @property
    def available(self) -> bool:
        return bool(self.login or self.password)

    def _pairs(self) -> list[tuple[str, str]]:
        pairs = [(self.password, PASSWORD), (self.login, LOGIN), (self.otp, OTP)]
        return [(v, t) for v, t in pairs if len(v) >= MIN_MASK_LEN]

    def expand(self, text: str) -> str:
        """Tokens -> real values (only at the moment of typing)."""
        for value, token in ((self.login, LOGIN), (self.password, PASSWORD), (self.otp, OTP)):
            text = text.replace(token, value)
        return text

    def uses_secret(self, text: str) -> list[str]:
        return [name for name, token in (("login", LOGIN), ("password", PASSWORD), ("OTP", OTP)) if token in text]

    def tokenize(self, text: str) -> str:
        """Real values -> tokens (what the LLM is allowed to see)."""
        for value, token in self._pairs():
            text = text.replace(value, token)
        return text

    def mask(self, text: str) -> str:
        """Real values -> *** (anything that may be stored or shown)."""
        for value, _ in self._pairs():
            text = text.replace(value, "***")
        if len(self.note) >= MIN_MASK_LEN:
            text = text.replace(self.note, "***")
        return text

    def llm_note(self) -> str:
        """The user's note with digits replaced by <OTP>, safe to show the model."""
        return _DIGITS.sub(OTP, self.note)

    def prompt_addendum(self) -> str:
        if not self.available:
            return ""
        parts = [
            "You have a test account. Log in with it when the app needs a login. Type the literal token "
            + f"{LOGIN} into the login field (email/phone/username) and {PASSWORD} into the password field"
        ]
        if self.otp:
            parts.append(f", and {OTP} into a one-time-code field")
        parts.append(". The harness replaces the tokens with the real values; never invent other credentials.")
        if self.note:
            parts.append(f" Note from the user: {self.llm_note()[:200]}")
        return "".join(parts)
