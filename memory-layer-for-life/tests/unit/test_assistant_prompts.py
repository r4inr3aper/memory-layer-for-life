"""What the assistant is told in chats and in scheduled runs."""

from app.services.assistant.prompts import Capabilities, chat_instructions, scheduled_instructions

EVERYTHING = Capabilities(browser=True, apps=True, memories=True)


def test_chats_can_browse_connect_apps_and_ask_for_confirmation() -> None:
    text = chat_instructions(EVERYTHING)

    assert "browse_web" in text
    assert "connect_app" in text
    assert "wait for the user to confirm" in text


def test_scheduled_runs_are_never_told_to_browse_even_when_a_browser_is_configured() -> None:
    assert "browse_web" not in scheduled_instructions(EVERYTHING)


def test_scheduled_runs_are_not_told_to_do_what_only_a_present_user_allows() -> None:
    text = scheduled_instructions(EVERYTHING)

    # Nobody can press a Connect button or confirm anything during a scheduled run.
    assert "connect_app" not in text
    assert "wait for the user to confirm" not in text
    assert "Apps cannot be connected during a scheduled run" in text
    assert "run_app_tool" in text


def test_without_apps_scheduled_runs_hear_nothing_about_them() -> None:
    text = scheduled_instructions(Capabilities(browser=True, apps=False, memories=False))

    assert "find_app_tools" not in text
    assert "Apps cannot be connected" not in text
    assert "search_memories" not in text
    assert "browse_web" not in text
