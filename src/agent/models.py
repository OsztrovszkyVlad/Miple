"""Model catalogue and hardware-based recommendation.

Sizes are the default (Q4_K_M) downloads from the Ollama library. The rule:

1. **Fits on the GPU** — the largest model whose working memory fits entirely
   in GPU memory (fast).
2. **Shared GPU + RAM** — Ollama splits a model across GPU and system RAM
   when it doesn't fit; this is fine for the small dense models, so the
   largest of those within GPU + 60 % of RAM is also a candidate.
3. The better of the two wins, as long as it fits on the disk.
"""
import logging
from dataclasses import dataclass

from src.actions.system import HardwareInfo

logger = logging.getLogger(__name__)

_RAM_SHARE = 0.6        # share of system RAM a model may use alongside the OS and apps
_APPLE_GPU_SHARE = 0.66  # macOS lets the GPU use about two-thirds of unified memory
_APPLE_SYSTEM_RESERVE_GB = 6.0  # keep room for macOS and the user's apps
_DISK_MARGIN_GB = 2.0


@dataclass(frozen=True)
class ModelOption:
    """A model Miple knows how to recommend."""

    tag: str
    label: str
    download_gb: float
    quality: int           # higher is better
    cpu_friendly: bool     # OK when partly or fully running on the CPU

    @property
    def working_gb(self) -> float:
        """Memory needed while running (weights + context + runtime overhead)."""
        return self.download_gb * 1.2 + 0.5


# Best first.
CATALOG: tuple[ModelOption, ...] = (
    ModelOption("gemma4:31b", "Gemma 4 31B", 20.0, 6, cpu_friendly=False),
    ModelOption("gemma4:26b", "Gemma 4 26B (MoE)", 18.0, 5, cpu_friendly=False),
    ModelOption("gemma4:12b", "Gemma 4 12B", 8.0, 4, cpu_friendly=False),
    ModelOption("gemma4:e4b", "Gemma 4 E4B", 6.6, 3, cpu_friendly=True),
    ModelOption("gemma4:e2b", "Gemma 4 E2B", 4.6, 2, cpu_friendly=True),
    ModelOption("gemma3:1b", "Gemma 3 1B", 0.8, 1, cpu_friendly=True),
)

SMALLEST = CATALOG[-1]


@dataclass(frozen=True)
class Recommendation:
    """The model picked for this machine, and why."""

    model: ModelOption
    reason: str


def find(tag: str) -> ModelOption | None:
    """Return the catalogue entry for *tag* (``gemma4:latest`` ≙ ``gemma4:e4b``)."""
    tag = {"gemma4:latest": "gemma4:e4b", "gemma4": "gemma4:e4b"}.get(tag, tag)
    return next((m for m in CATALOG if m.tag == tag), None)


def recommend(hw: HardwareInfo) -> Recommendation:
    """Pick the best model this machine can run comfortably."""
    gpu_mem = (
        min(hw.ram_gb * _APPLE_GPU_SHARE, hw.ram_gb - _APPLE_SYSTEM_RESERVE_GB)
        if hw.unified_memory
        else hw.vram_gb
    )
    disk_ok = [m for m in CATALOG if m.download_gb + _DISK_MARGIN_GB <= hw.free_disk_gb]
    if not disk_ok:
        return Recommendation(SMALLEST, "Your disk is almost full, so I picked the smallest model.")

    choice, fits_gpu = _pick(disk_ok, hw, gpu_mem)
    reason = _explain(choice, hw, fits_gpu=fits_gpu, gpu_mem=gpu_mem)
    if _pick(list(CATALOG), hw, gpu_mem)[0] is not choice:
        reason += " A bigger model would fit in memory, but not on your disk."
    logger.info("Recommended %s: %s", choice.tag, reason)
    return Recommendation(choice, reason)


def _pick(
    candidates: list[ModelOption], hw: HardwareInfo, gpu_mem: float
) -> tuple[ModelOption, bool]:
    """Return (best model, whether it runs fully on the GPU)."""
    shared_budget = gpu_mem + (0 if hw.unified_memory else hw.ram_gb * _RAM_SHARE)
    on_gpu = next((m for m in candidates if m.working_gb <= gpu_mem), None)
    shared = next(
        (m for m in candidates if m.cpu_friendly and m.working_gb <= shared_budget), None
    )
    choice = max((c for c in (on_gpu, shared) if c), key=lambda m: m.quality, default=None)
    if choice is None:
        return candidates[-1], False
    return choice, choice is on_gpu


def _explain(choice: ModelOption, hw: HardwareInfo, fits_gpu: bool, gpu_mem: float) -> str:
    if choice is SMALLEST and choice.working_gb > max(gpu_mem, hw.ram_gb * _RAM_SHARE):
        return "Your computer has little memory, so I picked the smallest model."
    if hw.unified_memory:
        return f"Fits in your Mac's {hw.ram_gb:.0f} GB of shared memory."
    if fits_gpu and gpu_mem > 0:
        return f"Runs fully on your graphics card ({gpu_mem:.0f} GB) for fast replies."
    if gpu_mem >= 1:
        return (
            f"Uses your graphics card ({gpu_mem:.0f} GB) together with your "
            f"{hw.ram_gb:.0f} GB of RAM."
        )
    return f"Runs on your processor using your {hw.ram_gb:.0f} GB of RAM (no graphics card found)."
