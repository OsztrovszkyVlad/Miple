"""AIManager — status and controls for the AI tab (Ollama + models).

Everything here runs off the GUI thread; results arrive through ``on_status``
as immutable :class:`AIStatus` snapshots. One operation runs at a time; new
requests while busy are ignored (the UI disables its buttons meanwhile).
"""
import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from src import config, settings
from src.actions import ollama_runtime
from src.actions.system import HardwareInfo, detect_hardware
from src.agent import models
from src.agent.ollama import InstalledModel, LoadedModel, OllamaClient

logger = logging.getLogger(__name__)

_START_WAIT_S = 30
_PROGRESS_STEP = 0.005


@dataclass(frozen=True)
class AIStatus:
    """Everything the AI tab shows."""

    installed: bool = False
    running: bool = False
    can_install: bool = False
    version: str | None = None
    current_model: str | None = None
    models: tuple[InstalledModel, ...] = ()
    loaded: tuple[LoadedModel, ...] = ()
    recommended: models.Recommendation | None = None
    hardware: str = ""
    busy: str | None = None        # what's happening right now, if anything
    progress: float | None = None  # 0–1 during downloads
    error: str | None = None       # last failure, shown until the next action

    @property
    def current_loaded(self) -> LoadedModel | None:
        """The current model's memory placement, if it's loaded."""
        return next((m for m in self.loaded if m.name == self.current_model), None)

    @property
    def recommended_installed(self) -> bool:
        """True if the recommended model is already downloaded."""
        rec = self.recommended
        if rec is None:
            return True
        return any(
            m.name == rec.model.tag or models.find(m.name) == rec.model for m in self.models
        )


class AIManager:
    """Inspect and control Ollama for the AI tab."""

    def __init__(
        self,
        on_status: Callable[[AIStatus], None],
        on_model_changed: Callable[[str], None] | None = None,
        client_factory: Callable[[], OllamaClient] = OllamaClient,
        hardware_probe: Callable[[], HardwareInfo] = detect_hardware,
        runtime=ollama_runtime,
        start_wait_s: float = _START_WAIT_S,
    ) -> None:
        """Create the manager; nothing runs until a method is called."""
        self._on_status = on_status
        self._on_model_changed = on_model_changed
        self._client_factory = client_factory
        self._hardware_probe = hardware_probe
        self._runtime = runtime
        self._start_wait_s = start_wait_s
        self._hw: HardwareInfo | None = None
        self._status = AIStatus()
        self._busy = threading.Lock()

    @property
    def status(self) -> AIStatus:
        """The latest snapshot."""
        return self._status

    # ------------------------------------------------------------------
    # Operations (each runs on a worker thread)
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Re-read Ollama's state (clears the last error)."""
        self._run("Checking…", self._refresh)

    def start_ollama(self) -> None:
        """Start the Ollama server and wait until it answers."""
        self._run("Starting Ollama…", self._start)

    def install_ollama(self) -> None:
        """Install Ollama (the user clicked Install), then refresh."""
        self._run(self._runtime.install_progress_text(), self._install)

    def use_model(self, name: str) -> None:
        """Switch to an installed model and load it."""
        self._run(f"Switching to {name}…", self._use, name)

    def download(self, tag: str) -> None:
        """Download *tag*, then switch to it."""
        self._run(f"Downloading {tag}…", self._download, tag)

    def warm_up(self) -> None:
        """Load the current model into memory so the next reply starts quickly."""
        self._run("Loading the AI model into memory…", self._load_current)

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        if self._hw is None:
            self._hw = self._hardware_probe()
        version, installed, loaded = asyncio.run(self._query())
        self._emit(
            installed=version is not None or self._runtime.find_ollama() is not None,
            running=version is not None,
            can_install=self._runtime.install_command() is not None,
            version=version,
            current_model=current_model(),
            models=tuple(installed or ()),
            loaded=tuple(loaded or ()),
            recommended=models.recommend(self._hw),
            hardware=self._hw.summary(),
        )

    def _start(self) -> None:
        if not self._runtime.start_server():
            self._fail("Ollama isn't installed yet.")
            return
        deadline = time.monotonic() + self._start_wait_s
        while asyncio.run(self._version()) is None and time.monotonic() < deadline:
            time.sleep(1)
        if asyncio.run(self._version()) is None:
            self._fail("Ollama didn't start. Try restarting your computer.")

    def _install(self) -> None:
        done = threading.Event()
        outcome: list[tuple[bool, str]] = []

        def finished(ok: bool, message: str) -> None:
            outcome.append((ok, message))
            done.set()

        self._runtime.install_ollama(dry_run=False, on_complete=finished)
        done.wait()
        ok, message = outcome[0]
        if not ok:
            self._fail(message)
            return
        self._start()

    def _use(self, name: str) -> None:
        settings.update(model=name)
        if self._on_model_changed:
            self._on_model_changed(name)
        self._load_current()

    def _download(self, tag: str) -> None:
        try:
            asyncio.run(self._pull(tag))
        except Exception as exc:
            logger.warning("Download of %s failed: %s", tag, exc)
            self._fail(f"The download stopped: {exc}")
            return
        self._use(tag)

    def _load_current(self) -> None:
        name = current_model()
        if name is None:
            return
        if not asyncio.run(self._call(lambda c: c.warm_up(name))):
            self._fail(f"Couldn't load {name}. Is Ollama running?")

    # ------------------------------------------------------------------
    # Async helpers (fresh client per call: each runs on its own event loop)
    # ------------------------------------------------------------------

    async def _call(self, fn):
        client = self._client_factory()
        try:
            return await fn(client)
        finally:
            await client.close()

    async def _version(self) -> str | None:
        return await self._call(lambda c: c.version())

    async def _query(self):
        async def all_three(c: OllamaClient):
            version = await c.version()
            if version is None:
                return None, None, None
            return version, await c.installed_models(), await c.loaded_models()

        return await self._call(all_three)

    async def _pull(self, tag: str) -> None:
        async def pull(c: OllamaClient) -> None:
            last = -1.0
            async for p in c.pull(tag):
                frac = p.fraction
                if frac is None or (frac - last < _PROGRESS_STEP and frac < 1):
                    continue
                last = frac
                self._emit(
                    busy=f"Downloading {tag}… {p.completed / 1024**3:.1f} of "
                         f"{p.total / 1024**3:.1f} GB",
                    progress=frac,
                )

        await self._call(pull)

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def _run(self, busy: str | None, target: Callable, *args) -> None:
        if not self._busy.acquire(blocking=False):
            logger.info("AI tab is busy; ignoring request")
            return

        def work() -> None:
            try:
                if busy:
                    self._emit(busy=busy, progress=None, error=None)
                target(*args)
                if target is not self._refresh:
                    self._refresh_keep_error()
            except Exception as exc:  # never let a worker die silently
                logger.error("AI tab operation failed: %s", exc, exc_info=True)
                self._fail(str(exc))
            finally:
                self._emit(busy=None, progress=None)
                self._busy.release()

        threading.Thread(target=work, name="miple-ai", daemon=True).start()

    def _refresh_keep_error(self) -> None:
        error = self._status.error
        self._refresh()
        if error:
            self._emit(error=error)

    def _fail(self, message: str) -> None:
        self._emit(error=message)

    def _emit(self, **fields) -> None:
        self._status = replace(self._status, **fields)
        self._on_status(self._status)


def current_model() -> str | None:
    """The model Miple uses: MIPLE_MODEL, else the one saved during setup."""
    return config.MODEL_OVERRIDE or settings.get("model")
