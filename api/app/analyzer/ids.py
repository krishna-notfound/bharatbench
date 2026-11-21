"""Finding id generation."""


def finding_id(run_id: str, rule_id: str, n: int) -> str:
    return f"{run_id[:8]}-{rule_id}-{n}"
