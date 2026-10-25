"""Small unit checks for chat turn confirmation detection."""

from app.services.chat_turns import _explicit_action_approval


def test_short_explicit_approval_is_accepted() -> None:
    assert _explicit_action_approval("Yes, go ahead") is True
    assert _explicit_action_approval("confirm") is True


def test_questions_or_negations_are_not_approvals() -> None:
    assert _explicit_action_approval("yes?") is False
    assert _explicit_action_approval("do not send it") is False
    assert _explicit_action_approval("cancel") is False


def test_long_or_unrelated_text_is_not_treated_as_approval() -> None:
    long_text = "yes " + ("please " * 20)
    assert _explicit_action_approval(long_text) is False
    assert _explicit_action_approval("what should we do next") is False
