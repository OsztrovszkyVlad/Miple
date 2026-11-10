"""Tests for AIManager (the AI tab's logic) and the Ollama client additions."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src import config, settings
from src.actions.system import HardwareInfo
from src.agent.ai_manager import AIManager, current_model
from src.agent.ollama import (
    _SLOW_ERROR, InstalledModel, LoadedModel, OllamaClient, PullProgress, is_error_message,
)


class FakeClient:
    def __init__(self, world):
        self.w = world

    async def version(self):
        return "0.40.16" if self.w.running else None

    async def installed_models(self):
        return [InstalledModel(n, 6.6) for n in self.w.models] if self.w.running else None

    async def loaded_models(self):
        return [LoadedModel(n, 7.0, 1.0) for n in self.w.loaded] if self.w.running else None

    async def warm_up(self, model=None):
        if not self.w.running:
            return False
        self.w.loaded = [model]
        return True

    async def pull(self, tag):
        if self.w.pull_error:
            raise RuntimeError(self.w.pull_error)
        for done in (0, 3, 6):
            yield PullProgress("pulling", done * 1024**3, 6 * 1024**3)
        self.w.models.append(tag)

    async def close(self):
        pass


class FakeRuntime:
    def __init__(self, world):
        self.w = world

    def find_ollama(self):
        return "ollama" if self.w.installed else None

    def start_server(self):
        if not self.w.installed:
            return False
        self.w.running = self.w.starts_ok
        return True

    def install_command(self):
        return ["winget"]

    def install_progress_text(self):
        return "Installing Ollama…"

    def install_ollama(self, dry_run=True, on_complete=None):
        self.w.installed = True
        on_complete(*self.w.install_result)
        return "started"


@pytest.fixture
def world():
    return SimpleNamespace(
        installed=True, running=True, starts_ok=True, models=["gemma4:e4b"], loaded=[],
        pull_error=None, install_result=(True, "Ollama installed."),
    )


class Statuses:
    """Collects statuses; wait() blocks until an operation has finished."""

    def __init__(self):
        self.all = []
        self._idle = threading.Event()

    def __call__(self, status):
        self.all.append(status)
        if status.busy is None:
            self._idle.set()

    def wait(self):
        assert self._idle.wait(5), "operation never finished"
        self._idle.clear()
        return self.all[-1]


def make(world, model_changes=None):
    statuses = Statuses()
    manager = AIManager(
        statuses,
        on_model_changed=(model_changes.append if model_changes is not None else None),
        client_factory=lambda: FakeClient(world),
        hardware_probe=lambda: HardwareInfo("Windows", 31, 24, 600),
        runtime=FakeRuntime(world),
        start_wait_s=0,
    )
    return manager, statuses


def test_refresh_connected(world):
    settings.update(model="gemma4:e4b")
    world.loaded = ["gemma4:e4b"]
    manager, statuses = make(world)
    manager.refresh()
    s = statuses.wait()
    assert s.running and s.installed and s.version == "0.40.16"
    assert s.current_model == "gemma4:e4b"
    assert s.current_loaded is not None
    assert s.recommended.model.tag == "gemma4:e4b" and s.recommended_installed
    assert "31 GB RAM" in s.hardware
    assert s.busy is None and s.error is None


def test_refresh_not_installed(world):
    world.installed = world.running = False
    manager, statuses = make(world)
    manager.refresh()
    s = statuses.wait()
    assert not s.installed and not s.running and s.can_install
    assert s.models == ()


def test_start_ollama(world):
    world.running = False
    manager, statuses = make(world)
    manager.start_ollama()
    s = statuses.wait()
    assert s.running and s.error is None
    assert any(x.busy == "Starting Ollama…" for x in statuses.all)


def test_start_ollama_failure_is_reported(world):
    world.running = False
    world.starts_ok = False
    manager, statuses = make(world)
    manager.start_ollama()
    s = statuses.wait()
    assert not s.running
    assert "didn't start" in s.error


def test_install_then_start(world):
    world.installed = world.running = False
    manager, statuses = make(world)
    manager.install_ollama()
    s = statuses.wait()
    assert s.installed and s.running


def test_install_failure_message(world):
    world.installed = world.running = False
    world.install_result = (False, "Ollama install failed (exit code 1).")
    manager, statuses = make(world)
    manager.install_ollama()
    assert "exit code 1" in statuses.wait().error


def test_use_model_saves_notifies_and_loads(world):
    world.models = ["gemma4:e4b", "llama3.2:3b"]
    changes = []
    manager, statuses = make(world, changes)
    manager.use_model("llama3.2:3b")
    s = statuses.wait()
    assert settings.get("model") == "llama3.2:3b"
    assert changes == ["llama3.2:3b"]
    assert s.current_model == "llama3.2:3b" and s.current_loaded is not None


def test_download_reports_progress_then_switches(world):
    world.models = []
    changes = []
    manager, statuses = make(world, changes)
    manager.download("gemma4:e4b")
    s = statuses.wait()
    progress = [x.progress for x in statuses.all if x.progress is not None]
    assert progress[0] == 0.0 and progress[-1] == 1.0
    assert any("3.0 of 6.0 GB" in (x.busy or "") for x in statuses.all)
    assert changes == ["gemma4:e4b"]
    assert s.current_model == "gemma4:e4b" and s.recommended_installed


def test_download_failure(world):
    world.pull_error = "connection reset"
    manager, statuses = make(world)
    manager.download("gemma4:e4b")
    assert "connection reset" in statuses.wait().error


def test_warm_up_when_ollama_down(world):
    settings.update(model="gemma4:e4b")
    world.running = False
    manager, statuses = make(world)
    manager.warm_up()
    assert "Couldn't load gemma4:e4b" in statuses.wait().error


def test_refresh_clears_previous_error(world):
    world.running = False
    world.starts_ok = False
    manager, statuses = make(world)
    manager.start_ollama()
    assert statuses.wait().error
    world.running = True
    manager.refresh()
    assert statuses.wait().error is None


def test_one_operation_at_a_time(world):
    gate = threading.Event()

    class SlowRuntime(FakeRuntime):
        def start_server(self):
            gate.wait(5)
            return super().start_server()

    world.running = False
    statuses = Statuses()
    manager = AIManager(
        statuses, client_factory=lambda: FakeClient(world),
        hardware_probe=lambda: HardwareInfo("Windows", 31, 24, 600),
        runtime=SlowRuntime(world), start_wait_s=0,
    )
    manager.start_ollama()
    manager.refresh()  # ignored: busy
    gate.set()
    statuses.wait()
    assert not any(x.busy == "Checking…" for x in statuses.all)


def test_current_model_prefers_override(monkeypatch):
    settings.update(model="gemma4:e4b")
    assert current_model() == "gemma4:e4b"
    monkeypatch.setattr(config, "MODEL_OVERRIDE", "mistral:7b")
    assert current_model() == "mistral:7b"


# ---------------------------------------------------------------------------
# OllamaClient additions
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def _resp(data):
    r = MagicMock()
    r.json.return_value = data
    r.raise_for_status = MagicMock()
    return r


def test_loaded_models_placement():
    client = OllamaClient()
    data = {"models": [
        {"name": "gemma4:e4b", "size": 8 * 1024**3, "size_vram": 8 * 1024**3},
        {"name": "big", "size": 20 * 1024**3, "size_vram": 5 * 1024**3},
        {"name": "cpu", "size": 2 * 1024**3, "size_vram": 0},
    ]}
    with patch.object(client._client, "get", new=AsyncMock(return_value=_resp(data))):
        loaded = run(client.loaded_models())
    assert [m.placement for m in loaded] == ["GPU", "25% GPU / 75% CPU", "CPU"]


def test_installed_models_sizes_and_version():
    client = OllamaClient()
    tags = _resp({"models": [{"name": "gemma4:e4b", "size": 7_086_696_448}]})
    with patch.object(client._client, "get", new=AsyncMock(return_value=tags)):
        assert run(client.installed_models()) == [InstalledModel("gemma4:e4b", 6.6)]
    with patch.object(client._client, "get", new=AsyncMock(side_effect=httpx.ConnectError("x"))):
        assert run(client.version()) is None
        assert run(client.installed_models()) is None


def test_slow_model_gets_honest_message():
    client = OllamaClient()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
    cm.__aexit__ = AsyncMock(return_value=False)

    async def collect():
        return [t async for t in client.chat([{"role": "user", "content": "hi"}])]

    with patch.object(client._client, "stream", return_value=cm), \
         patch.object(client, "get_model", new=AsyncMock(return_value="gemma4:e4b")):
        tokens = run(collect())
    assert tokens == [_SLOW_ERROR]
    assert is_error_message(_SLOW_ERROR)
    assert "connect" not in _SLOW_ERROR


def test_chat_and_warm_up_ask_to_stay_loaded():
    client = OllamaClient()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("down"))
    cm.__aexit__ = AsyncMock(return_value=False)
    stream = MagicMock(return_value=cm)

    async def collect():
        return [t async for t in client.chat([{"role": "user", "content": "hi"}])]

    with patch.object(client._client, "stream", stream), \
         patch.object(client, "get_model", new=AsyncMock(return_value="gemma4:e4b")):
        run(collect())
    assert stream.call_args.kwargs["json"]["keep_alive"] == config.KEEP_ALIVE

    post = AsyncMock(return_value=_resp({}))
    with patch.object(client._client, "post", new=post):
        assert run(client.warm_up("gemma4:e4b")) is True
    assert post.call_args.kwargs["json"] == {"model": "gemma4:e4b", "keep_alive": config.KEEP_ALIVE}


def test_system_prompt_fits_agent_loop():
    from src.agent.ollama import SYSTEM_PROMPT

    assert "Always end your reply with an action block" not in SYSTEM_PROMPT
    assert "[Action result]" in SYSTEM_PROMPT
    assert "WITHOUT an action block" in SYSTEM_PROMPT
