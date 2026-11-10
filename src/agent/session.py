"""AssistantSession — conversation state, the agent loop and background execution.

Owns the chat history, the Ollama client and a single long-lived asyncio
event loop running on a daemon thread. The UI calls :meth:`submit` /
:meth:`confirm` from the GUI thread and receives results through callbacks,
which are invoked on a worker thread (the UI must marshal them back, e.g. with
Qt signals).

Agent loop
----------
One user message may take several model calls ("steps"). After each action
runs, its result is added to the history as a message and the model is asked
again, until one of these happens:

* the model replies without an action (or with a no-op action) — done;
* the action needs the user's confirmation (destructive) — stop and wait;
* the model repeats an action it already ran this turn — stop, so a model
  that keeps emitting the same block can't e.g. launch an app five times;
* ``max_steps`` model calls have been made (default 5);
* Ollama fails.

Each step is written as one JSON line to the step log (:mod:`step_log`).
"""
import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.agent import actions, parser
from src.agent.ollama import OllamaClient, is_error_message
from src.agent.step_log import StepLog

logger = logging.getLogger(__name__)

_MAX_HISTORY_MESSAGES = 20  # keep the prompt small for 4B-class local models
MAX_AGENT_STEPS = 5

# Why a turn's loop ended (logged on the last step of the turn).
STOP_NO_ACTION = "no_action"
STOP_CONFIRMATION = "needs_confirmation"
STOP_REPEAT = "repeated_action"
STOP_STEP_LIMIT = "step_limit"
STOP_ERROR = "model_error"

_RESULT_NOTE = (
    "(Automatic message from Miple, not from the user.) "
    "Reply to the user. Add another action block only if more is needed to finish the request."
)


@dataclass
class Reply:
    """What the assistant produced for one user message."""

    text: str
    """Prose to show in the chat (action blocks removed), joined across steps. May be empty."""

    action: actions.ActionResult | None = None
    """The last action result of the turn — the one awaiting confirmation, if any."""

    is_error: bool = False
    """True when Ollama couldn't be reached or returned an error."""

    steps: list[actions.ActionResult] = field(default_factory=list)
    """Every action result produced this turn, in order (``action`` is the last)."""

    stop_reason: str = STOP_NO_ACTION
    """Why the agent loop ended (one of the ``STOP_*`` constants)."""


@dataclass
class _Step:
    """Outcome of one model call (+ action) inside the loop."""

    response: str
    prose: str = ""
    action: dict | None = None
    result: actions.ActionResult | None = None
    started: float = 0.0


class AssistantSession:
    """Run chat turns and confirmed actions off the GUI thread."""

    def __init__(
        self,
        client: OllamaClient | None = None,
        max_steps: int = MAX_AGENT_STEPS,
        step_log: StepLog | Path | None = None,
    ) -> None:
        """Start the background event loop and create the Ollama client.

        Args:
            client: Ollama client (created inside the loop if omitted).
            max_steps: Maximum model calls per user message.
            step_log: Where to log steps (a StepLog, a file path, or the default file).
        """
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="miple-asyncio", daemon=True
        )
        self._thread.start()
        self._client = client or self._call_in_loop(OllamaClient)
        self._max_steps = max(1, max_steps)
        self._step_log = step_log if isinstance(step_log, StepLog) else StepLog(step_log)
        self._history: list[dict] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(self, text: str, on_reply: Callable[[Reply], None]) -> None:
        """Send *text* to the model; *on_reply* is called once with the result."""
        future = asyncio.run_coroutine_threadsafe(self._turn(text), self._loop)
        future.add_done_callback(lambda f: on_reply(_result_or_error(f)))

    def confirm(
        self,
        pending_action: dict,
        on_result: Callable[[actions.ActionResult], None],
    ) -> None:
        """Execute a previewed destructive action in the background.

        *on_result* receives the immediate result and, for long-running
        actions such as installs, a second result when they finish.
        """
        def work() -> None:
            on_result(actions.confirm(pending_action, on_complete=_as_result(on_result)))

        threading.Thread(target=work, name="miple-confirm", daemon=True).start()

    def set_model(self, model: str) -> None:
        """Switch the model used for the following turns."""
        self._client.set_model(model)

    def history(self) -> list[dict]:
        """Return a copy of the conversation so far."""
        with self._lock:
            return list(self._history)

    def reset(self) -> None:
        """Forget the conversation."""
        with self._lock:
            self._history.clear()

    def shutdown(self) -> None:
        """Close the HTTP client and stop the event loop."""
        try:
            asyncio.run_coroutine_threadsafe(self._client.close(), self._loop).result(2)
        except Exception as exc:  # shutting down — never raise
            logger.debug("Error closing Ollama client: %s", exc)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)

    # ------------------------------------------------------------------
    # Agent loop
    # ------------------------------------------------------------------

    async def _turn(self, text: str) -> Reply:
        """Run the agent loop for one user message."""
        turn_id = uuid.uuid4().hex[:12]
        self._append({"role": "user", "content": text})
        prose: list[str] = []
        results: list[actions.ActionResult] = []
        seen: list[dict] = []
        for number in range(1, self._max_steps + 1):
            step = await self._call_model()
            if is_error_message(step.response):
                self._log(turn_id, number, step, STOP_ERROR)
                return self._error_reply(step.response, prose, results, first=number == 1)
            if step.prose:
                prose.append(step.prose)
            stop = await self._run_action(step, seen, number)
            if step.result is not None:
                results.append(step.result)
            self._log(turn_id, number, step, stop)
            if stop:
                return _reply(prose, results, stop)
        raise AssertionError("unreachable: the last step always stops")  # pragma: no cover

    async def _call_model(self) -> _Step:
        """Ask the model for the next step and record its answer in the history."""
        started = time.monotonic()
        with self._lock:
            messages = self._history[-_MAX_HISTORY_MESSAGES:]
        response = "".join([token async for token in self._client.chat(messages)])
        logger.debug("Model output: %r", response)
        step = _Step(response=response, started=started)
        if not is_error_message(response):
            self._append({"role": "assistant", "content": response})
            step.action, step.prose = parser.split_action(response)
        return step

    async def _run_action(self, step: _Step, seen: list[dict], number: int) -> str | None:
        """Dispatch the step's action; return a stop reason, or None to continue."""
        if step.action is None:
            return STOP_NO_ACTION
        normalized = actions.normalize(step.action)
        if normalized["action"] == actions.NO_ACTION:
            return STOP_NO_ACTION
        if normalized in seen:
            logger.info("Model repeated %s; stopping the loop", normalized["action"])
            return STOP_REPEAT
        seen.append(normalized)
        result = await asyncio.to_thread(actions.dispatch, step.action)
        if not result.message:  # unknown action: nothing happened
            return STOP_NO_ACTION
        step.result = result
        self._append(_result_message(normalized["action"], result))
        if result.needs_confirmation:
            return STOP_CONFIRMATION
        if number >= self._max_steps:
            return STOP_STEP_LIMIT
        return None

    def _error_reply(
        self, error: str, prose: list[str], results: list, first: bool
    ) -> Reply:
        """Build the reply for an Ollama failure mid-turn."""
        if first:
            with self._lock:
                self._history.pop()  # don't keep a turn the model never saw
            return Reply(error, is_error=True, stop_reason=STOP_ERROR)
        reply = _reply(prose + [error], results, STOP_ERROR)
        reply.is_error = True
        return reply

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _append(self, message: dict) -> None:
        with self._lock:
            self._history.append(message)

    def _log(self, turn_id: str, number: int, step: _Step, stop: str | None) -> None:
        """Write one JSON line describing *step*."""
        result = step.result
        self._step_log.write({
            "turn": turn_id,
            "step": number,
            "model_output": step.response,
            "action": step.action,
            "result": None if result is None else {
                "message": result.message,
                "needs_confirmation": result.needs_confirmation,
            },
            "duration_s": round(time.monotonic() - step.started, 3),
            "stop_reason": stop,
        })

    def _call_in_loop(self, factory: Callable):
        """Construct an object inside the event loop thread."""
        async def make():
            return factory()

        return asyncio.run_coroutine_threadsafe(make(), self._loop).result()


def _result_message(action: str, result: actions.ActionResult) -> dict:
    """The history message that tells the model what its action did."""
    status = (
        "NOT done yet: the user was shown this preview and must confirm it."
        if result.needs_confirmation
        else "Done."
    )
    body = json.dumps({"action": action, "status": status, "result": result.message}, ensure_ascii=False)
    return {"role": "user", "content": f"[Action result] {body}\n{_RESULT_NOTE}"}


def _reply(prose: list[str], results: list[actions.ActionResult], stop: str) -> Reply:
    """Assemble the turn's reply."""
    return Reply(
        "\n\n".join(p for p in prose if p),
        action=results[-1] if results else None,
        steps=list(results),
        stop_reason=stop,
    )


def _result_or_error(future) -> Reply:
    """Unwrap a finished future, turning unexpected exceptions into a Reply."""
    try:
        return future.result()
    except Exception as exc:
        logger.error("Chat turn failed: %s", exc, exc_info=True)
        return Reply(f"Something went wrong: {exc}", is_error=True)


def _as_result(on_result: Callable[[actions.ActionResult], None]) -> Callable[[str], None]:
    """Adapt a message callback to an ActionResult callback."""
    return lambda message: on_result(actions.ActionResult(message))
