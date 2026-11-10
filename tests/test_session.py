"""Tests for AssistantSession (src.agent.session), including the agent loop."""
import json
import threading

import pytest

from src.agent import session as session_mod
from src.agent.ollama import _FRIENDLY_ERROR
from src.agent.session import AssistantSession, Reply


class FakeClient:
    """Stands in for OllamaClient.

    Takes canned responses, or one callable ``(call_number) -> str`` for an
    endless supply. Records the messages of every call.
    """

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.seen: list[list[dict]] = []

    @property
    def calls(self) -> int:
        return len(self.seen)

    async def chat(self, messages):
        self.seen.append(list(messages))
        if len(self.responses) == 1 and callable(self.responses[0]):
            yield self.responses[0](self.calls)
            return
        assert self.responses, f"model called more often than expected ({self.calls} calls)"
        yield self.responses.pop(0)

    async def close(self):
        pass


def note(content: str, prose: str = "Saving.") -> str:
    """A model reply that asks to save a note (a safe, immediate action)."""
    return f"{prose} {{action: 'save_note', params: {{content: '{content}'}}}}"


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
def step_log_path(tmp_path):
    return tmp_path / "agent-steps.jsonl"


@pytest.fixture
def make_session(step_log_path):
    sessions = []

    def factory(*responses, max_steps=session_mod.MAX_AGENT_STEPS):
        s = AssistantSession(
            client=FakeClient(*responses), max_steps=max_steps, step_log=step_log_path
        )
        sessions.append(s)
        return s

    yield factory
    for s in sessions:
        s.shutdown()


def read_log(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_multiple_turns_share_one_loop(make_session):
    """Regression: the old UI ran each turn on a fresh event loop."""
    session = make_session("Hi!", "Hello again!")
    assert _ask(session, "hello").text == "Hi!"
    assert _ask(session, "again").text == "Hello again!"
    assert [m["role"] for m in session.history()] == ["user", "assistant", "user", "assistant"]


def test_action_is_dispatched_and_stripped(make_session, isolated_notes_dir):
    session = make_session(note("buy milk", prose="Got it!"), "Saved it for you.")
    reply = _ask(session, "remind me to buy milk")
    assert reply.text == "Got it!\n\nSaved it for you."
    assert reply.action is not None and "Note saved" in reply.action.message
    assert len(list(isolated_notes_dir.glob("*.md"))) == 1


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def test_loop_feeds_results_back_until_no_action(make_session, isolated_notes_dir):
    session = make_session(note("first"), note("second"), "Both notes are saved.")
    reply = _ask(session, "save two notes")
    client = session._client

    assert client.calls == 3
    assert reply.stop_reason == session_mod.STOP_NO_ACTION
    assert [r.message.startswith("Note saved") for r in reply.steps] == [True, True]
    assert reply.action is reply.steps[-1]
    assert reply.text.endswith("Both notes are saved.")
    assert len(list(isolated_notes_dir.glob("*.md"))) == 2

    # Call 2 saw the result of action 1 as the newest message.
    feedback = client.seen[1][-1]
    assert feedback["role"] == "user"
    assert feedback["content"].startswith("[Action result]")
    assert '"action": "save_note"' in feedback["content"]
    assert "Done." in feedback["content"]
    roles = [m["role"] for m in session.history()]
    assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]


def test_loop_stops_at_step_limit(make_session, isolated_notes_dir):
    session = make_session(lambda n: note(f"note {n}"))  # always asks for another action
    reply = _ask(session, "keep going")

    assert session._client.calls == session_mod.MAX_AGENT_STEPS == 5
    assert reply.stop_reason == session_mod.STOP_STEP_LIMIT
    assert len(reply.steps) == 5
    assert len(list(isolated_notes_dir.glob("*.md"))) == 5


def test_step_limit_is_configurable(make_session):
    session = make_session(lambda n: note(f"note {n}"), max_steps=2)
    reply = _ask(session, "keep going")
    assert session._client.calls == 2
    assert reply.stop_reason == session_mod.STOP_STEP_LIMIT


def test_destructive_action_stops_loop_for_confirmation(make_session, tmp_path):
    folder = tmp_path / "downloads"
    folder.mkdir()
    (folder / "song.mp3").write_text("x")
    organize = f"Here's my plan. {{\"action\": \"organize_files\", \"params\": {{\"path\": \"{folder.as_posix()}\"}}}}"
    session = make_session(organize, "This must never be requested.")

    reply = _ask(session, "tidy my downloads")

    assert session._client.calls == 1  # loop did not continue
    assert reply.stop_reason == session_mod.STOP_CONFIRMATION
    assert reply.action.needs_confirmation
    assert reply.action.pending_action["action"] == "organize_files"
    assert (folder / "song.mp3").exists()  # nothing moved before confirmation
    feedback = session.history()[-1]["content"]
    assert "NOT done yet" in feedback  # the model will know it was only a preview


def test_safe_step_then_confirmation(make_session, tmp_path, isolated_notes_dir):
    folder = tmp_path / "dl"
    folder.mkdir()
    (folder / "a.pdf").write_text("x")
    organize = f"{{\"action\": \"organize_files\", \"params\": {{\"path\": \"{folder.as_posix()}\"}}}}"
    session = make_session(note("plan"), organize, "unused")
    reply = _ask(session, "note it, then tidy")
    assert session._client.calls == 2
    assert [r.needs_confirmation for r in reply.steps] == [False, True]
    assert reply.stop_reason == session_mod.STOP_CONFIRMATION


def test_repeated_action_is_not_run_twice(make_session, isolated_notes_dir):
    session = make_session(note("milk"), note("milk"), "unused")
    reply = _ask(session, "remind me")
    assert session._client.calls == 2
    assert reply.stop_reason == session_mod.STOP_REPEAT
    assert len(reply.steps) == 1
    assert len(list(isolated_notes_dir.glob("*.md"))) == 1


def test_noop_action_ends_loop(make_session):
    session = make_session("Happy to help! {action: 'none'}", "unused")
    reply = _ask(session, "hi")
    assert session._client.calls == 1
    assert reply.text == "Happy to help!"
    assert reply.steps == [] and reply.action is None


def test_error_mid_loop_keeps_earlier_steps(make_session, isolated_notes_dir):
    session = make_session(note("milk", prose="On it."), _FRIENDLY_ERROR)
    reply = _ask(session, "remind me")
    assert reply.is_error
    assert reply.stop_reason == session_mod.STOP_ERROR
    assert len(reply.steps) == 1
    assert reply.text.startswith("On it.") and _FRIENDLY_ERROR in reply.text
    assert all(_FRIENDLY_ERROR not in m["content"] for m in session.history())


# ---------------------------------------------------------------------------
# Step log
# ---------------------------------------------------------------------------

def test_each_step_is_logged_as_one_json_line(make_session, step_log_path, isolated_notes_dir):
    session = make_session(note("first"), "All done.")
    _ask(session, "save a note")

    records = read_log(step_log_path)
    assert [r["step"] for r in records] == [1, 2]
    assert len({r["turn"] for r in records}) == 1
    first, last = records
    assert first["model_output"] == note("first")
    assert first["action"] == {"action": "save_note", "params": {"content": "first"}}
    assert first["result"]["message"].startswith("Note saved")
    assert first["result"]["needs_confirmation"] is False
    assert first["stop_reason"] is None
    assert last["action"] is None and last["result"] is None
    assert last["stop_reason"] == session_mod.STOP_NO_ACTION
    for r in records:
        assert isinstance(r["duration_s"], float) and r["duration_s"] >= 0
        assert r["ts"].endswith("+00:00")


def test_step_log_failure_does_not_break_turn(make_session, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    s = AssistantSession(client=FakeClient("Hi!"), step_log=blocker / "log.jsonl")
    try:
        assert _ask(s, "hello").text == "Hi!"
    finally:
        s.shutdown()


def test_default_step_log_lives_in_config_dir(isolated_settings):
    from src.agent.step_log import StepLog

    assert StepLog().path == isolated_settings / "agent-steps.jsonl"


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
