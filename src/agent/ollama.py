"""Ollama API client — async, streaming, fail-safe."""
import json
import logging
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are Miple, a Linux AI assistant. Always end your reply with an action block.\n"
    "Examples:\n"
    "User: search for cats → Sure! {action: 'google_search', params: {query: 'cats'}}\n"
    "User: open vlc → Opening VLC! {action: 'open_app', params: {name: 'vlc'}}\n"
    "User: open terminal → Opening terminal! {action: 'open_app', params: {name: 'terminal'}}\n"
    "User: install vlc → Installing VLC! {action: 'install_app', params: {name: 'vlc'}}\n"
    "User: organize downloads → {action: 'organize_files', params: {path: '~/Downloads'}}\n"
    "User: open files → Opening file manager! {action: 'open_app', params: {name: 'files'}}\n"
    "User: fix error → Paste your error and I'll explain it. {action: 'explain_error', params: {error_text: 'the error'}}\n"
    "User: remind me to buy milk → Got it! {action: 'save_note', params: {content: 'buy milk', title: 'reminder'}}\n"
    "Always include the action block. Keep replies under 2 sentences."
)

_FRIENDLY_ERROR = (
    "I couldn't connect to Ollama. "
    "Make sure Ollama is running (`ollama serve`) and try again."
)

_DEFAULT_MODEL = "gemma4:e4b"


class OllamaClient:
    """Async HTTP client for the Ollama /api/chat endpoint.

    Never raises unhandled exceptions — all errors produce a friendly
    message yielded back to callers via the chat() async generator.
    """

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        """Create the client.

        Args:
            base_url: Base URL of the Ollama server.
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)

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
        """Return the model to use — prefers gemma4:e4b, falls back to first available."""
        try:
            resp = await self._client.get(f"{self._base_url}/api/tags")
            resp.raise_for_status()
            models: list[dict] = resp.json().get("models", [])
            names = [m["name"] for m in models if "name" in m]
            if _DEFAULT_MODEL in names:
                return _DEFAULT_MODEL
            if names:
                logger.info("gemma4:e4b not found; using %s", names[0])
                return names[0]
        except Exception as exc:
            logger.warning("Could not fetch model list: %s", exc)
        return _DEFAULT_MODEL

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
        payload = {"model": model, "messages": full_messages, "stream": stream}
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
                    if data.get("done"):
                        break
                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content
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
