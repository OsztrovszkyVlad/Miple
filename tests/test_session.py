"""Tests for AssistantSession (src.agent.session)."""
import threading

import pytest

from src.agent.ollama import _FRIENDLY_ERROR
from src.agent.session import AssistantSession, Reply


class FakeClient:
    """Stands in for OllamaClient; yields canned responses."""

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.seen: list[list[dict]] = []

    async def chat(self, messages):
        self.seen.append(list(messages))
        yield self.responses.pop(0)

    async def close(self):
        pass


def _ask(session: AssistantSession, text: str) -> Reply:
    done = threading.Event()
    box: list[Reply] = []

    def on_reply(reply):
        box.append(reply)
        done.set()

    session.submit(text, on_reply)
    assert done.wait(5), "no reply within 5s"
    return box[0]


@pytest.fixture
def make_session():
    sessions = []

    def factory(*responses):
        s = AssistantSession(client=FakeClient(*responses))
        sessions.append(s)
        return s

    yield factory
    for s in sessions:
        s.shutdown()


def test_multiple_turns_share_one_loop(make_session):
    """Regression: the old UI ran each turn on a fresh event loop."""
    session = make_session("Hi!", "Hello again!")
    assert _ask(session, "hello").text == "Hi!"
    assert _ask(session, "again").text == "Hello again!"
    assert [m["role"] for m in session.history()] == ["user", "assistant", "user", "assistant"]


def test_action_is_dispatched_and_stripped(make_session, isolated_notes_dir):
    session = make_session("Got it! {action: 'save_note', params: {content: 'buy milk'}}")
    reply = _ask(session, "remind me to buy milk")
    assert reply.text == "Got it!"
    assert reply.action is not None and "Note saved" in reply.action.message
    assert len(list(isolated_notes_dir.glob("*.md"))) == 1


def test_errors_are_not_kept_in_history(make_session):
    session = make_session(_FRIENDLY_ERROR)
    reply = _ask(session, "hello")
    assert reply.is_error
    assert session.history() == []


def test_confirm_runs_in_background(make_session, tmp_path):
    (tmp_path / "song.mp3").write_text("x")
    session = make_session()
    done = threading.Event()
    results = []

    def on_result(result):
        results.append(result)
        done.set()

    session.confirm({"action": "organize_files", "params": {"path": str(tmp_path)}}, on_result)
    assert done.wait(5)
    assert "Moved 1 files" in results[0].message
    assert (tmp_path / "music" / "song.mp3").exists()
