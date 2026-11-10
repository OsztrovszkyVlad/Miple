"""First-run and start-up setup: make sure Ollama runs and a fitting model exists.

Runs on every launch. When everything is in place it finishes silently in a
second or two. It only stops to ask the user when a decision is needed:

* Ollama is not installed → offer *Install Ollama* (a system change).
* The recommended model is not downloaded → offer *Download (N GB)*.

Everything else — starting the Ollama server, choosing the model from the
detected hardware, remembering the choice — happens automatically.

States are reported through ``on_state`` from worker threads; the UI must
marshal them to its own thread.
"""
import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum

from src import config, settings
from src.actions import ollama_runtime
from src.actions.system import HardwareInfo, detect_hardware
from src.agent import models
from src.agent.ollama import OllamaClient

logger = logging.getLogger(__name__)

_START_WAIT_S = 30
_PROGRESS_STEP = 0.005  # emit download progress every 0.5 %


class Stage(Enum):
    """Where setup is."""

    CHECKING = "checking"
    STARTING_OLLAMA = "starting_ollama"
    NEED_OLLAMA = "need_ollama"
    INSTALLING_OLLAMA = "installing_ollama"
    NEED_MODEL = "need_model"
    DOWNLOADING = "downloading"
    READY = "ready"
    ERROR = "error"


@dataclass(frozen=True)
class SetupState:
    """Snapshot of setup progress for the UI."""

    stage: Stage
    message: str
    hardware: str = ""
    progress: float | None = None  # 0–1, or None for "busy, unknown progress"
    primary: str | None = None     # label of the main button, if any
    secondary: str | None = None   # label of the second button, if any
    model: str | None = None       # recommended or selected model tag

    @property
    def busy(self) -> bool:
        """True while setup is working and no button applies."""
        return self.stage in (
            Stage.CHECKING, Stage.STARTING_OLLAMA, Stage.INSTALLING_OLLAMA, Stage.DOWNLOADING
        )


class SetupFlow:
    """Drive setup; button clicks are forwarded to :meth:`primary` / :meth:`secondary`."""

    def __init__(
        self,
        on_state: Callable[[SetupState], None],
        client_factory: Callable[[], OllamaClient] = OllamaClient,
        hardware_probe: Callable[[], HardwareInfo] = detect_hardware,
        runtime=ollama_runtime,
        start_wait_s: float = _START_WAIT_S,
    ) -> None:
        """Create the flow (call :meth:`start` to begin)."""
        self._on_state = on_state
        self._client_factory = client_factory
        self._hardware_probe = hardware_probe
        self._runtime = runtime
        self._start_wait_s = start_wait_s
        self._hw: HardwareInfo | None = None
        self._state = SetupState(Stage.CHECKING, "Checking your computer…")
        self._installed: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> SetupState:
        """The latest state."""
        return self._state

    def start(self) -> None:
        """Run the checks in the background."""
        self._spawn(self._check)

    def primary(self) -> None:
        """Handle the main button for the current stage."""
        stage = self._state.stage
        if stage is Stage.NEED_OLLAMA and self._runtime.install_command():
            self._spawn(self._install_ollama)
        elif stage is Stage.NEED_MODEL and self._state.model:
            self._spawn(self._download, self._state.model)
        elif stage in (Stage.NEED_OLLAMA, Stage.ERROR):
            self.start()

    def secondary(self) -> None:
        """Handle the second button: 'Retry' or 'Use <installed model>'."""
        stage = self._state.stage
        if stage is Stage.NEED_MODEL and self._installed:
            self._spawn(self._use_model, self._installed[0])
        else:
            self.start()

    # ------------------------------------------------------------------
    # Steps (run on worker threads)
    # ------------------------------------------------------------------

    def _check(self) -> None:
        self._emit(Stage.CHECKING, "Checking your computer…")
        if self._hw is None:
            self._hw = self._hardware_probe()
        installed = asyncio.run(self._list_models())
        if installed is None:
            installed = self._bring_up_ollama()
            if installed is None:
                return
        self._installed = installed
        self._choose_model(installed)

    def _bring_up_ollama(self) -> list[str] | None:
        """Start (or offer to install) Ollama; return installed models once it answers."""
        if self._runtime.find_ollama() is None:
            can_install = self._runtime.install_command() is not None
            self._emit(
                Stage.NEED_OLLAMA,
                "Miple needs Ollama, the free program that runs the AI on your computer."
                + ("" if can_install else "\n\n" + self._runtime.manual_install_hint()),
                primary="Install Ollama" if can_install else None,
                secondary="Retry",
            )
            return None
        self._emit(Stage.STARTING_OLLAMA, "Starting Ollama…")
        self._runtime.start_server()
        installed = asyncio.run(self._wait_for_server())
        if installed is None:
            self._error("Ollama is installed but didn't start. Try restarting your computer.")
        return installed

    def _choose_model(self, installed: list[str]) -> None:
        if config.MODEL_OVERRIDE:
            self._ready_or_offer(config.MODEL_OVERRIDE, installed, "You chose this model (MIPLE_MODEL).")
            return
        saved = settings.get("model")
        if saved and saved in installed:
            self._ready(saved)
            return
        rec = models.recommend(self._hw)
        self._ready_or_offer(rec.model.tag, installed, rec.reason)

    def _ready_or_offer(self, tag: str, installed: list[str], reason: str) -> None:
        match = _installed_name(tag, installed)
        if match:
            self._use_model(match)
            return
        option = models.find(tag)
        label = option.label if option else tag
        size = f" ({option.download_gb:.1f} GB)" if option else ""
        self._emit(
            Stage.NEED_MODEL,
            f"Best model for your computer: {label}{size}.\n{reason}",
            primary=f"Download{size}",
            secondary=f"Use {installed[0]} instead" if installed else None,
            model=tag,
        )

    def _download(self, tag: str) -> None:
        option = models.find(tag)
        label = option.label if option else tag
        self._emit(Stage.DOWNLOADING, f"Downloading {label}…", progress=0.0, model=tag)
        try:
            asyncio.run(self._pull(tag, label))
        except Exception as exc:
            logger.warning("Download of %s failed: %s", tag, exc)
            self._error(f"The download stopped: {exc}. Check your internet connection.")
            return
        self._use_model(tag)

    def _install_ollama(self) -> None:
        self._emit(Stage.INSTALLING_OLLAMA, "Installing Ollama… confirm the system prompt if one appears.")

        def done(ok: bool, message: str) -> None:
            if ok:
                self._check()
            else:
                self._error(message + "\n\n" + self._runtime.manual_install_hint())

        self._runtime.install_ollama(dry_run=False, on_complete=done)

    def _use_model(self, tag: str) -> None:
        settings.update(model=tag)
        self._ready(tag)

    def _ready(self, tag: str) -> None:
        self._emit(Stage.READY, f"Ready — using {tag}.", model=tag)

    def _error(self, message: str) -> None:
        self._emit(Stage.ERROR, message, primary="Retry")

    # ------------------------------------------------------------------
    # Async helpers (each runs on its own short-lived event loop)
    # ------------------------------------------------------------------

    async def _list_models(self) -> list[str] | None:
        client = self._client_factory()
        try:
            return await client.list_models()
        finally:
            await client.close()

    async def _wait_for_server(self) -> list[str] | None:
        deadline = time.monotonic() + self._start_wait_s
        while True:
            installed = await self._list_models()
            if installed is not None or time.monotonic() >= deadline:
                return installed
            await asyncio.sleep(1)

    async def _pull(self, tag: str, label: str) -> None:
        client = self._client_factory()
        last = -1.0
        try:
            async for p in client.pull(tag):
                frac = p.fraction
                if frac is None or frac - last < _PROGRESS_STEP and frac < 1:
                    continue
                last = frac
                done_gb, total_gb = p.completed / 1024**3, p.total / 1024**3
                self._emit(
                    Stage.DOWNLOADING,
                    f"Downloading {label}… {done_gb:.1f} of {total_gb:.1f} GB",
                    progress=frac,
                    model=tag,
                )
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # Plumbing
    # ------------------------------------------------------------------

    def _emit(self, stage: Stage, message: str, **fields) -> None:
        hardware = self._hw.summary() if self._hw else ""
        self._state = replace(
            SetupState(stage, message), hardware=hardware, **fields
        )
        logger.debug("Setup: %s — %s", stage.value, message)
        self._on_state(self._state)

    def _spawn(self, target: Callable, *args) -> None:
        threading.Thread(target=target, args=args, name="miple-setup", daemon=True).start()


def _installed_name(tag: str, installed: list[str]) -> str | None:
    """Return the installed name matching *tag* (``x`` also matches ``x:latest``)."""
    for name in installed:
        if name == tag or name == f"{tag}:latest" or (
            models.find(name) is not None and models.find(name) == models.find(tag)
        ):
            return name
    return None
