"""Ollama API client — async, streaming, fail-safe."""
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from src import config

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Miple, a friendly assistant running on the user's own computer.\n"
    "You can act by ending your reply with ONE action block, for example:\n"
    "User: search for cats → Sure! {action: 'google_search', params: {query: 'cats'}}\n"
    "User: open vlc → Opening VLC! {action: 'open_app', params: {name: 'vlc'}}\n"
    "User: open files → Opening the file manager! {action: 'open_app', params: {name: 'files'}}\n"
    "User: install vlc → I'll install VLC. {action: 'install_app', params: {name: 'vlc'}}\n"
    "User: organize downloads → Here's my plan. {action: 'organize_files', params: {path: '~/Downloads'}}\n"
    "User: <pasted error> → Let me look. {action: 'explain_error', params: {error_text: '<the error>'}}\n"
    "User: remind me to buy milk → Got it! {action: 'save_note', params: {content: 'buy milk', title: 'reminder'}}\n"
    "Rules:\n"
    "- Only add an action block when the user's request needs one. For questions and chat, just answer.\n"
    "- After an action runs you get a message starting with [Action result]. It comes from Miple, "
    "not the user. Then tell the user what happened in one short sentence WITHOUT an action block, "
    "unless another, different action is still needed.\n"
    "- Never repeat an action that already succeeded.\n"
    "- If a result says the user must confirm, just say they can review the plan and click "
    "'Yes, do it'.\n"
    "Keep replies under 2 sentences."
)

_FRIENDLY_ERROR = (
    "I couldn't connect to Ollama. "
    "Open the AI tab to start it, or check that Ollama is running."
)

_SLOW_ERROR = (
    "The AI model is taking longer than expected — it may still be loading into memory. "
    "Please try again in a moment."
)

_MODEL_MISSING_PREFIX = "Ollama doesn't have the model"

_DEFAULT_MODEL = config.DEFAULT_MODEL


@dataclass(frozen=True)
class PullProgress:
    """One progress update from a model download."""

    status: str
    completed: int = 0
    total: int = 0

    @property
    def fraction(self) -> float | None:
        """0–1 while bytes are downloading, else None."""
        return self.completed / self.total if self.total else None


@dataclass(frozen=True)
class InstalledModel:
    """A model downloaded into Ollama."""

    name: str
    size_gb: float


@dataclass(frozen=True)
class LoadedModel:
    """A model currently loaded in memory (from /api/ps)."""

    name: str
    size_gb: float
    gpu_share: float  # 0–1, how much of it sits in graphics memory

    @property
    def placement(self) -> str:
        """'GPU', 'CPU' or e.g. '62% GPU / 38% CPU'."""
        if self.gpu_share >= 0.99:
            return "GPU"
        if self.gpu_share <= 0.01:
            return "CPU"
        gpu = round(self.gpu_share * 100)
        return f"{gpu}% GPU / {100 - gpu}% CPU"


def is_error_message(text: str) -> bool:
    """Return True if *text* is one of the client's user-facing error messages."""
    return text in (_FRIENDLY_ERROR, _SLOW_ERROR) or text.startswith(_MODEL_MISSING_PREFIX)


def _http_error_message(exc: httpx.HTTPStatusError, model: str) -> str:
    """Turn an HTTP error from Ollama into a friendly chat message."""
    if exc.response.status_code == 404:
        return (
            f"{_MODEL_MISSING_PREFIX} '{model}'. "
            f"Install it with `ollama pull {model}` and try again."
        )
    return _FRIENDLY_ERROR


class OllamaClient:
    """Async HTTP client for the Ollama /api/chat endpoint.

    Never raises unhandled exceptions — all errors produce a friendly
    message yielded back to callers via the chat() async generator.
    """

    def __init__(self, base_url: str = config.OLLAMA_URL) -> None:
        """Create the client.

        Args:
            base_url: Base URL of the Ollama server.
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.REQUEST_TIMEOUT, connect=5.0)
        )
        self._model: str | None = None

    # ------------------------------------------------------------------
    # Availability & model detection
    # ------------------------------------------------------------------

    async def check_available(self) -> bool:
        """Return True if the Ollama server is reachable, False otherwise."""
        try:
            resp = await self._client.get(f"{self._base_url}/api/tags")
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Ollama availability check failed: %s", exc)
            return False

    async def get_model(self) -> str:
        """Return the model to use — prefers the default, falls back to first available.

        The result is cached after the first successful lookup.
        """
        if self._model is None:
            self._model = await self._detect_model()
        return self._model or _DEFAULT_MODEL

    def set_model(self, model: str) -> None:
        """Use *model* from now on (e.g. the one chosen during setup)."""
        logger.info("Using model %s", model)
        self._model = model

    async def list_models(self) -> list[str] | None:
        """Return installed model names, or None if Ollama can't be reached."""
        try:
            resp = await self._client.get(f"{self._base_url}/api/tags")
            resp.raise_for_status()
            models: list[dict] = resp.json().get("models", [])
        except Exception as exc:
            logger.warning("Could not fetch model list: %s", exc)
            return None
        return [m["name"] for m in models if "name" in m]

    @property
    def model(self) -> str | None:
        """The model explicitly chosen or detected so far (None if not yet known)."""
        return self._model

    async def version(self) -> str | None:
        """Ollama's version string, or None if it can't be reached."""
        data = await self._get_json("/api/version")
        return data.get("version") if data else None

    async def installed_models(self) -> list[InstalledModel] | None:
        """Downloaded models with their sizes, or None if Ollama can't be reached."""
        data = await self._get_json("/api/tags")
        if data is None:
            return None
        return [
            InstalledModel(m["name"], round(int(m.get("size") or 0) / 1024**3, 1))
            for m in data.get("models", [])
            if "name" in m
        ]

    async def loaded_models(self) -> list[LoadedModel] | None:
        """Models currently in memory, or None if Ollama can't be reached."""
        data = await self._get_json("/api/ps")
        if data is None:
            return None
        loaded = []
        for m in data.get("models", []):
            size = int(m.get("size") or 0)
            vram = int(m.get("size_vram") or 0)
            share = vram / size if size else 0.0
            loaded.append(LoadedModel(m.get("name", "?"), round(size / 1024**3, 1), min(share, 1.0)))
        return loaded

    async def warm_up(self, model: str | None = None) -> bool:
        """Load *model* (default: the current one) into memory so replies start fast.

        Returns True when the model is loaded. Can take minutes the first time.
        """
        model = model or await self.get_model()
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/generate",
                json={"model": model, "keep_alive": config.KEEP_ALIVE},
                timeout=httpx.Timeout(config.LOAD_TIMEOUT, connect=5.0),
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Could not load %s: %s", model, exc)
            return False
        logger.info("Model %s loaded", model)
        return True

    async def _get_json(self, path: str) -> dict | None:
        try:
            resp = await self._client.get(f"{self._base_url}{path}", timeout=5.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("GET %s failed: %s", path, exc)
            return None

    async def pull(self, model: str) -> AsyncIterator[PullProgress]:
        """Download *model*, yielding progress updates.

        Raises:
            httpx.HTTPError / RuntimeError: if the download fails.
        """
        url = f"{self._base_url}/api/pull"
        timeout = httpx.Timeout(None, connect=10.0)  # big downloads take a while
        async with self._client.stream(
            "POST", url, json={"model": model, "stream": True}, timeout=timeout
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if "error" in data:
                    raise RuntimeError(data["error"])
                yield PullProgress(
                    status=data.get("status", ""),
                    completed=int(data.get("completed") or 0),
                    total=int(data.get("total") or 0),
                )

    async def _detect_model(self) -> str | None:
        """Pick the default model, else the first installed one."""
        names = await self.list_models()
        if not names:
            if names == []:
                logger.warning("Ollama has no models installed")
            return None
        if _DEFAULT_MODEL in names:
            return _DEFAULT_MODEL
        logger.info("%s not found; using %s", _DEFAULT_MODEL, names[0])
        return names[0]

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    async def chat(
        self, messages: list[dict], stream: bool = True
    ) -> AsyncIterator[str]:
        """Send *messages* to Ollama and yield response tokens.

        Prepends the system prompt if not already present.
        On any error, yields a friendly error string and returns.

        Args:
            messages: List of {"role": str, "content": str} dicts.
            stream: Whether to stream the response token-by-token.

        Yields:
            Response text tokens (or a single error string on failure).
        """
        full_messages = self._with_system_prompt(messages)
        model = await self.get_model()
        payload = {
            "model": model,
            "messages": full_messages,
            "stream": stream,
            "keep_alive": config.KEEP_ALIVE,  # stay loaded between messages
        }
        try:
            if stream:
                async for token in self._stream(payload):
                    yield token
            else:
                content = await self._fetch_full(payload)
                yield content
        except Exception as exc:
            logger.warning("chat() error: %s", exc, exc_info=True)
            yield _FRIENDLY_ERROR

    async def _stream(self, payload: dict) -> AsyncIterator[str]:
        """Stream response tokens from /api/chat."""
        url = f"{self._base_url}/api/chat"
        try:
            async with self._client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
                    # No `break` on "done": Ollama ends the stream right after it, and
                    # reading to the end lets httpx close the response cleanly.
        except httpx.HTTPStatusError as exc:
            logger.warning("Ollama returned an error: %s", exc)
            yield _http_error_message(exc, payload.get("model", ""))
        except (httpx.ReadTimeout, httpx.PoolTimeout, httpx.WriteTimeout) as exc:
            # Connected, but the model didn't answer in time (usually still loading).
            logger.warning("Ollama didn't answer within %ss: %r", config.REQUEST_TIMEOUT, exc)
            yield _SLOW_ERROR
        except Exception as exc:
            logger.warning("Streaming error: %s", exc, exc_info=True)
            yield _FRIENDLY_ERROR

    async def _fetch_full(self, payload: dict) -> str:
        """Fetch a complete (non-streamed) response from /api/chat."""
        url = f"{self._base_url}/api/chat"
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _with_system_prompt(messages: list[dict]) -> list[dict]:
        """Prepend system prompt if the first message is not already system."""
        if messages and messages[0].get("role") == "system":
            return messages
        return [{"role": "system", "content": SYSTEM_PROMPT}] + list(messages)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "OllamaClient":
        """Support async context manager."""
        return self

    async def __aexit__(self, *args) -> None:
        """Close client on context exit."""
        await self.close()
