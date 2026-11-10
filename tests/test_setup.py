"""Tests for hardware detection, model choice, settings and the setup flow."""
import threading
from types import SimpleNamespace

import pytest

from src import settings
from src.actions import system
from src.actions.system import GPU, HardwareInfo
from src.agent import models
from src.agent.ollama import PullProgress
from src.agent.setup import SetupFlow, Stage


def hw(ram=16, vram=0, disk=500, apple=False, name="GPU"):
    gpus = (GPU(name, vram, "nvidia"),) if vram else ()
    return HardwareInfo("Linux", ram, 8, disk, gpus, unified_memory=apple)


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        (hw(ram=8), "gemma3:1b"),                 # small laptop, no GPU
        (hw(ram=12), "gemma4:e2b"),
        (hw(ram=16), "gemma4:e4b"),               # project minimum spec, CPU only
        (hw(ram=16, vram=4), "gemma4:e4b"),       # project minimum spec with GPU
        (hw(ram=32, vram=8), "gemma4:e4b"),       # e.g. RTX 4060 laptop
        (hw(ram=32, vram=12), "gemma4:12b"),
        (hw(ram=32, vram=16), "gemma4:12b"),
        (hw(ram=64, vram=24), "gemma4:26b"),      # RTX 3090/4090
        (hw(ram=64, vram=48), "gemma4:31b"),
        (hw(ram=16, apple=True), "gemma4:e4b"),   # M-series 16 GB
        (hw(ram=36, apple=True), "gemma4:26b"),
        (hw(ram=128, vram=0), "gemma4:e4b"),      # lots of RAM but CPU only: keep it fast
    ],
)
def test_recommend(machine, expected):
    assert models.recommend(machine).model.tag == expected


def test_recommend_respects_disk_space():
    rec = models.recommend(hw(ram=64, vram=24, disk=12))
    assert rec.model.tag == "gemma4:12b"
    assert "disk" in rec.reason


def test_recommend_full_disk():
    rec = models.recommend(hw(ram=64, vram=24, disk=1))
    assert rec.model is models.SMALLEST


def test_find_handles_latest_alias():
    assert models.find("gemma4:latest").tag == "gemma4:e4b"
    assert models.find("mistral") is None


# ---------------------------------------------------------------------------
# Hardware probes
# ---------------------------------------------------------------------------

def test_parse_nvidia_smi():
    out = "NVIDIA GeForce RTX 4060 Laptop GPU, 8188\nNVIDIA A100, 81920\n"
    gpus = system.parse_nvidia_smi(out)
    assert gpus[0] == GPU("NVIDIA GeForce RTX 4060 Laptop GPU", 8.0, "nvidia")
    assert gpus[1].vram_gb == 80.0


def test_linux_amd_sysfs(tmp_path):
    card = tmp_path / "card1" / "device"
    card.mkdir(parents=True)
    (card / "mem_info_vram_total").write_text(str(16 * 1024**3))
    apu = tmp_path / "card0" / "device"
    apu.mkdir(parents=True)
    (apu / "mem_info_vram_total").write_text(str(512 * 1024**2))  # iGPU carve-out
    assert system._linux_amd_gpus(tmp_path) == [GPU("AMD Radeon", 16.0, "amd")]


def test_summary():
    machine = hw(ram=31.1, vram=8, name="NVIDIA GeForce RTX 4060 Laptop GPU")
    assert machine.summary() == "31 GB RAM · RTX 4060 Laptop (8 GB) · 8 threads"
    assert "no dedicated GPU" in hw(ram=8).summary()


def test_detect_hardware_runs_here():
    info = system.detect_hardware()
    assert info.ram_gb > 0
    assert info.cpu_threads >= 1


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def test_settings_roundtrip(isolated_settings):
    assert settings.load() == {}
    settings.update(model="gemma4:e4b")
    settings.update(other=1)
    assert settings.get("model") == "gemma4:e4b"
    assert settings.settings_path().parent == isolated_settings


def test_corrupt_settings_ignored(isolated_settings):
    isolated_settings.mkdir(parents=True)
    (isolated_settings / "settings.json").write_text("{nope", encoding="utf-8")
    assert settings.load() == {}


# ---------------------------------------------------------------------------
# Setup flow
# ---------------------------------------------------------------------------

class FakeClient:
    """Shared state across the short-lived clients SetupFlow creates."""

    def __init__(self, world):
        self.world = world

    async def list_models(self):
        return list(self.world.models) if self.world.running else None

    async def pull(self, tag):
        if self.world.pull_error:
            raise RuntimeError(self.world.pull_error)
        for done in (0, 1, 2):
            yield PullProgress("downloading", done * 1024**3, 2 * 1024**3)
        self.world.models.append(tag)

    async def close(self):
        pass


class FakeRuntime:
    def __init__(self, world):
        self.world = world
        self.started = 0

    def find_ollama(self):
        return "/usr/bin/ollama" if self.world.installed else None

    def start_server(self):
        self.started += 1
        self.world.running = self.world.starts_ok
        return True

    def install_command(self):
        return ["install"] if self.world.can_install else None

    def manual_install_hint(self):
        return "Get it from ollama.com"

    def install_progress_text(self):
        return "Installing Ollama…"

    def install_ollama(self, dry_run=True, on_complete=None):
        self.world.installed = True
        self.world.running = True
        on_complete(True, "Ollama installed.")
        return "Installing…"


@pytest.fixture
def world():
    return SimpleNamespace(
        installed=True, running=True, starts_ok=True, can_install=True,
        models=[], pull_error=None,
    )


class Recorder:
    def __init__(self):
        self.states = []
        self.event = threading.Event()
        self.waiting_for = None

    def __call__(self, state):
        self.states.append(state)
        if self.waiting_for and state.stage in self.waiting_for:
            self.event.set()

    def wait(self, *stages):
        self.event.clear()
        self.waiting_for = stages
        if self.states and self.states[-1].stage in stages:
            return self.states[-1]
        assert self.event.wait(5), f"never reached {stages}; got {[s.stage for s in self.states]}"
        return self.states[-1]


def make_flow(world, machine=None):
    rec = Recorder()
    runtime = FakeRuntime(world)
    flow = SetupFlow(
        rec,
        client_factory=lambda: FakeClient(world),
        hardware_probe=lambda: machine or hw(ram=32, vram=8),
        runtime=runtime,
        start_wait_s=0,
    )
    return flow, rec, runtime


def test_ready_immediately_when_model_present(world):
    world.models = ["gemma4:e4b"]
    flow, rec, _ = make_flow(world)
    flow.start()
    state = rec.wait(Stage.READY)
    assert state.model == "gemma4:e4b"
    assert settings.get("model") == "gemma4:e4b"
    assert not any(s.primary for s in rec.states)  # never asked the user anything


def test_saved_model_wins(world):
    world.models = ["llama3.2:3b", "gemma4:e4b"]
    settings.update(model="llama3.2:3b")
    flow, rec, _ = make_flow(world)
    flow.start()
    assert rec.wait(Stage.READY).model == "llama3.2:3b"


def test_starts_ollama_automatically(world):
    world.running = False
    world.models = ["gemma4:e4b"]
    flow, rec, runtime = make_flow(world)
    flow.start()
    rec.wait(Stage.READY)
    assert runtime.started == 1
    assert Stage.STARTING_OLLAMA in [s.stage for s in rec.states]


def test_ollama_fails_to_start(world):
    world.running = False
    world.starts_ok = False
    flow, rec, _ = make_flow(world)
    flow.start()
    assert rec.wait(Stage.ERROR).primary == "Retry"


def test_install_then_download(world):
    world.installed = world.running = False
    flow, rec, _ = make_flow(world)
    flow.start()
    need = rec.wait(Stage.NEED_OLLAMA)
    assert need.primary == "Install Ollama"

    flow.primary()
    offer = rec.wait(Stage.NEED_MODEL)
    assert offer.model == "gemma4:e4b"
    assert offer.primary == "Download (6.6 GB)"
    assert offer.secondary is None  # nothing installed to fall back on
    assert "31" not in offer.message or "graphics card" in offer.message

    flow.primary()
    ready = rec.wait(Stage.READY)
    assert ready.model == "gemma4:e4b"
    progress = [s.progress for s in rec.states if s.stage is Stage.DOWNLOADING]
    assert progress[0] == 0.0 and progress[-1] == 1.0


def test_manual_install_when_no_installer(world):
    world.installed = world.running = False
    world.can_install = False
    flow, rec, _ = make_flow(world)
    flow.start()
    state = rec.wait(Stage.NEED_OLLAMA)
    assert state.primary is None
    assert state.secondary == "Retry"
    assert "ollama.com" in state.message


def test_use_installed_model_instead(world):
    world.models = ["llama3.2:3b"]
    flow, rec, _ = make_flow(world)
    flow.start()
    offer = rec.wait(Stage.NEED_MODEL)
    assert offer.secondary == "Use llama3.2:3b instead"
    flow.secondary()
    assert rec.wait(Stage.READY).model == "llama3.2:3b"


def test_download_failure_offers_retry(world):
    world.pull_error = "network unreachable"
    flow, rec, _ = make_flow(world)
    flow.start()
    rec.wait(Stage.NEED_MODEL)
    flow.primary()
    state = rec.wait(Stage.ERROR)
    assert "network unreachable" in state.message
    world.pull_error = None
    flow.primary()  # Retry → checks again → offers the download again
    rec.wait(Stage.NEED_MODEL)


def test_model_override(world, monkeypatch):
    from src import config

    monkeypatch.setattr(config, "MODEL_OVERRIDE", "mistral:7b")
    world.models = ["mistral:7b", "gemma4:e4b"]
    flow, rec, _ = make_flow(world)
    flow.start()
    assert rec.wait(Stage.READY).model == "mistral:7b"


def test_latest_tag_counts_as_installed(world):
    world.models = ["gemma4:latest"]
    flow, rec, _ = make_flow(world)
    flow.start()
    assert rec.wait(Stage.READY).model == "gemma4:latest"


# ---------------------------------------------------------------------------
# Ollama runtime install helpers
# ---------------------------------------------------------------------------

def test_install_runs_without_console_window(monkeypatch):
    import subprocess
    from src.actions import ollama_runtime

    calls = {}

    def fake_run(cmd, **kw):
        calls.update(kw)
        return subprocess.CompletedProcess(cmd, 0, "Successfully installed", "")

    monkeypatch.setattr(ollama_runtime.subprocess, "run", fake_run)
    monkeypatch.setattr(ollama_runtime.sys, "platform", "win32")
    monkeypatch.setattr(ollama_runtime.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    results = []
    ollama_runtime._run_install(["winget"], lambda ok, msg: results.append((ok, msg)))
    assert calls["creationflags"] == 0x08000000
    assert calls["stdin"] is subprocess.DEVNULL
    assert results == [(True, "Ollama installed.")]


def test_describe_failure_skips_progress_noise():
    import subprocess
    from src.actions.ollama_runtime import describe_failure

    out = (
        "Found Ollama [Ollama.Ollama] Version 0.40.16\n"
        "Downloading https://github.com/ollama/ollama/releases/download/v0.40.16/OllamaSetup.exe\n"
        "  ██████████▒▒▒▒  500 MB / 1.2 GB\n"
        "Installer failed with exit code: 1603\n"
    )
    result = subprocess.CompletedProcess(["winget"], -1978335226, out, "")
    assert describe_failure(result) == (
        "Installer failed with exit code: 1603; exit code -1978335226 / 0x8A150006"
    )
    only_noise = subprocess.CompletedProcess(["winget"], 1, "Downloading x\n", "")
    assert describe_failure(only_noise) == "exit code 1"
