import json

from harness.agent import parse_action, verdict


def _act(text: str) -> dict:
    act = parse_action(text, 5)
    assert act is not None
    return act


def test_done_with_met_true_and_positive_reason_passes():
    assert verdict(_act('{"action":"done","met":true,"reason":"Results for browser are listed"}')) is True


def test_done_with_met_false_fails():
    assert verdict(_act('{"action":"done","met":false,"reason":"Nothing happened"}')) is False


def test_done_whose_reason_says_not_met_fails_even_without_met_flag():
    reason = "The search results show 'No matching applications available.' so the success check is not met"
    assert verdict(_act(json.dumps({"action": "done", "reason": reason}))) is False


def test_fail_action_is_never_a_pass():
    assert verdict(_act('{"action":"fail","reason":"Stuck on loading"}')) is False
