"""Unit tests for OllamaClient and extract_action."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.ollama import OllamaClient, _FRIENDLY_ERROR, is_error_message
from src.agent.parser import extract_action


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


def _mock_response(status: int = 200, json_data: dict | None = None) -> MagicMock:
    """Return a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


def _ndjson_lines(*payloads: dict) -> list[str]:
    """Build a list of NDJSON line strings."""
    return [json.dumps(p) for p in payloads]


# ---------------------------------------------------------------------------
# check_available
# ---------------------------------------------------------------------------

def test_check_available_true():
    """Returns True when /api/tags responds 200."""
    client = OllamaClient()
    resp = _mock_response(200)
    with patch.object(client._client, "get", new=AsyncMock(return_value=resp)):
        result = run(client.check_available())
    assert result is True


def test_check_available_false():
    """Returns False (no exception) when connection is refused."""
    import httpx
    client = OllamaClient()
    with patch.object(
        client._client, "get", new=AsyncMock(side_effect=httpx.ConnectError("refused"))
    ):
        result = run(client.check_available())
    assert result is False


# ---------------------------------------------------------------------------
# get_model
# ---------------------------------------------------------------------------

def test_get_model_prefers_gemma():
    """Returns gemma4:e4b when it's in the model list."""
    client = OllamaClient()
    resp = _mock_response(200, {"models": [{"name": "gemma4:e4b"}, {"name": "llama3"}]})
    with patch.object(client._client, "get", new=AsyncMock(return_value=resp)):
        result = run(client.get_model())
    assert result == "gemma4:e4b"


def test_get_model_fallback():
    """Returns first available model when gemma4:e4b is absent."""
    client = OllamaClient()
    resp = _mock_response(200, {"models": [{"name": "llama3:latest"}]})
    with patch.object(client._client, "get", new=AsyncMock(return_value=resp)):
        result = run(client.get_model())
    assert result == "llama3:latest"


def test_get_model_error():
    """Returns default model string when Ollama is unreachable."""
    import httpx
    client = OllamaClient()
    with patch.object(
        client._client, "get", new=AsyncMock(side_effect=httpx.ConnectError("no route"))
    ):
        result = run(client.get_model())
    assert result == "gemma4:e4b"


# ---------------------------------------------------------------------------
# chat — streaming
# ---------------------------------------------------------------------------

def _make_stream_context(lines: list[str]):
    """Build a mock async context manager that yields NDJSON lines."""
    async def aiter_lines():
        for line in lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.aiter_lines = aiter_lines

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def test_chat_streams_tokens():
    """Yields all content tokens from a streaming response."""
    lines = _ndjson_lines(
        {"message": {"content": "Hello"}, "done": False},
        {"message": {"content": " world"}, "done": False},
        {"message": {"content": "!"}, "done": True},
    )
    client = OllamaClient()
    cm = _make_stream_context(lines)

    # Also mock get_model so it doesn't hit network.
    async def _collect():
        tokens = []
        async for token in client.chat([{"role": "user", "content": "hi"}]):
            tokens.append(token)
        return tokens

    with patch.object(client._client, "stream", return_value=cm), \
         patch.object(client, "get_model", new=AsyncMock(return_value="gemma4:e4b")):
        tokens = run(_collect())

    assert tokens == ["Hello", " world", "!"]  # content on the done chunk is kept


def test_chat_connection_error():
    """Yields the friendly error string on ConnectError — no exception raised."""
    import httpx
    client = OllamaClient()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("refused"))
    cm.__aexit__ = AsyncMock(return_value=False)

    async def _collect():
        tokens = []
        async for token in client.chat([{"role": "user", "content": "hi"}]):
            tokens.append(token)
        return tokens

    with patch.object(client._client, "stream", return_value=cm), \
         patch.object(client, "get_model", new=AsyncMock(return_value="gemma4:e4b")):
        tokens = run(_collect())

    assert len(tokens) == 1
    assert "Ollama" in tokens[0]
    assert tokens[0] == _FRIENDLY_ERROR


# ---------------------------------------------------------------------------
# extract_action
# ---------------------------------------------------------------------------

def test_extract_action_found():
    """Parses a well-formed action block into a dict."""
    text = "Sure! {action: 'organize_files', params: {path: '~/Downloads'}} Done."
    result = extract_action(text)
    assert result == {"action": "organize_files", "params": {"path": "~/Downloads"}}


def test_extract_action_none():
    """Returns None for plain text with no action block."""
    result = extract_action("Hello, how can I help you today?")
    assert result is None


def test_extract_action_malformed():
    """Returns None (no exception) for a broken action-like string."""
    result = extract_action("{action: 'broken', params: {unclosed")
    assert result is None


def test_get_model_is_cached():
    """The model list is fetched once, not on every message."""
    client = OllamaClient()
    resp = _mock_response(200, {"models": [{"name": "llama3:latest"}]})
    get = AsyncMock(return_value=resp)
    with patch.object(client._client, "get", new=get):
        run(client.get_model())
        run(client.get_model())
    assert get.await_count == 1


def test_get_model_not_cached_on_failure():
    """A failed lookup is retried next time instead of being cached."""
    import httpx
    client = OllamaClient()
    get = AsyncMock(side_effect=httpx.ConnectError("down"))
    with patch.object(client._client, "get", new=get):
        run(client.get_model())
        run(client.get_model())
    assert get.await_count == 2


def test_chat_missing_model_message():
    """A 404 from Ollama tells the user which model to pull."""
    import httpx
    client = OllamaClient()
    request = httpx.Request("POST", "http://x/api/chat")
    response = httpx.Response(404, request=request)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("404", request=request, response=response)
    )
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)

    async def _collect():
        return [t async for t in client.chat([{"role": "user", "content": "hi"}])]

    with patch.object(client._client, "stream", return_value=cm), \
         patch.object(client, "get_model", new=AsyncMock(return_value="gemma4:e4b")):
        tokens = run(_collect())

    assert len(tokens) == 1
    assert "ollama pull gemma4:e4b" in tokens[0]
    assert is_error_message(tokens[0])
