"""Convert harness steps into a Maestro YAML flow."""

import re

from app.models import HarnessScreen, HarnessStep

_POINT = re.compile(r"^\d+\s*,\s*\d+$")


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _tap(target: str | None) -> str | None:
    if not target:
        return None
    if _POINT.match(target):
        return f"- tapOn: {{point: {_q(target.replace(' ', ''))}}}"
    if ":id/" in target:
        return f"- tapOn: {{id: {_q(target.split(':id/', 1)[1])}}}"
    return f"- tapOn: {_q(target)}"


def steps_to_maestro(package: str, steps: list[HarnessStep], screens: list[HarnessScreen]) -> str:
    lines = [f"appId: {package}", "---", "- launchApp"]
    for step in sorted(steps, key=lambda s: s.index):
        line: str | None = None
        if step.action == "tap":
            line = _tap(step.target)
        elif step.action == "back":
            line = "- back"
        elif step.action == "background":
            line = "- pressKey: Home"
        elif step.action == "kill":
            line = "- stopApp"
        elif step.action == "restore":
            line = "- launchApp"
        if line:
            lines.append(line)
    return "\n".join(lines) + "\n"
