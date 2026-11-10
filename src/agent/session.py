"""AssistantSession — conversation state and background execution.

Owns the chat history, the Ollama client and a single long-lived asyncio
event loop running on a daemon thread. The UI calls :meth:`submit` /
:meth:`confirm` from the GUI thread and receives results through callbacks,
which are invoked on a worker thread (the UI must marshal them back, e.g. with
Qt signals).
"""
import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from src.agent import actions, parser
from src.agent.ollama import OllamaClient, is_error_message

logger = logging.getLogger(__name__)

_MAX_HISTORY_MESSAGES = 20  # keep the prompt small for 4B-class local models


@dataclass
class Reply:
    """What the assistant produced for one user message."""

    text: str
    """Prose to show in the chat (action block removed). May be empty."""

    action: actions.ActionResult | None = None
    """Result of the action the model asked for, if any."""

    is_error: bool = False
    """True when Ollama couldn't be reached or returned an error."""


class AssistantSession:
    """Run chat turns and confirmed actions off the GUI thread."""

    def __init__(self, client: OllamaClient | None = None) -> None:
        """Start the background event loop and create the Ollama client."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="miple-asyncio", daemon=True
        )
        self._thread.start()
        self._client = client or self._call_in_loop(OllamaClient)
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
    # Internals
    # ------------------------------------------------------------------

    async def _turn(self, text: str) -> Reply:
        """Run one user → model → action round trip."""
        with self._lock:
            self._history.append({"role": "user", "content": text})
            messages = self._history[-_MAX_HISTORY_MESSAGES:]
        response = "".join([token async for token in self._client.chat(messages)])
        logger.debug("Full response: %r", response)

        if is_error_message(response):
            with self._lock:
                self._history.pop()  # don't keep a turn the model never saw
            return Reply(response, is_error=True)

        with self._lock:
            self._history.append({"role": "assistant", "content": response})
        action_dict, prose = parser.split_action(response)
        result = None
        if action_dict is not None:
            result = await asyncio.to_thread(actions.dispatch, action_dict)
        return Reply(prose, action=result)

    def _call_in_loop(self, factory: Callable):
        """Construct an object inside the event loop thread."""
        async def make():
            return factory()

        return asyncio.run_coroutine_threadsafe(make(), self._loop).result()


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
