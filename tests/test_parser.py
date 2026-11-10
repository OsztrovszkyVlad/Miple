"""Tests for src.agent.parser."""
from src.agent.parser import extract_action, split_action, strip_action


def test_strict_json():
    text = 'On it! {"action": "open_app", "params": {"name": "vlc"}}'
    assert extract_action(text) == {"action": "open_app", "params": {"name": "vlc"}}


def test_js_style_literal():
    text = "Sure! {action: 'organize_files', params: {path: '~/Downloads'}} Done."
    action, prose = split_action(text)
    assert action == {"action": "organize_files", "params": {"path": "~/Downloads"}}
    assert prose == "Sure!  Done."


def test_trailing_comma():
    assert extract_action("{action: 'open_app', params: {name: 'vlc',},}") == {
        "action": "open_app",
        "params": {"name": "vlc"},
    }


def test_value_with_colon_and_comma():
    text = "{action: 'save_note', params: {content: 'call Bob at 5:30, bring docs'}}"
    assert extract_action(text)["params"]["content"] == "call Bob at 5:30, bring docs"


def test_skips_non_action_braces():
    text = 'Use {braces} carefully. {"action": "google_search", "params": {"query": "x"}}'
    action, prose = split_action(text)
    assert action["action"] == "google_search"
    assert prose == "Use {braces} carefully."


def test_no_action():
    assert split_action("  Hello there!  ") == (None, "Hello there!")


def test_malformed():
    assert extract_action("{action: 'broken', params: {unclosed") is None


def test_strip_action_leaves_prose():
    assert strip_action("Opening VLC! {action: 'open_app', params: {name: 'vlc'}}") == (
        "Opening VLC!"
    )
