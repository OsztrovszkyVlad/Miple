"""System detection — RAM, GPU memory, CPU and free disk, without extra packages.

Linux is the primary target (``/proc``, ``sysfs``); Windows (Win32 API +
registry) and macOS (``sysctl``) are supported so the same detection works
everywhere Miple runs. Every probe is best-effort: a failure yields 0 / None,
never an exception.
"""
import ctypes
import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_GIB = 1024**3


@dataclass(frozen=True)
class GPU:
    """One graphics card."""

    name: str
    vram_gb: float
    vendor: str  # "nvidia" | "amd" | "intel" | "apple" | "other"


@dataclass(frozen=True)
class HardwareInfo:
    """What the computer can offer a local AI model."""

    os: str
    ram_gb: float
    cpu_threads: int
    free_disk_gb: float
    gpus: tuple[GPU, ...] = field(default_factory=tuple)
    unified_memory: bool = False  # Apple silicon: GPU shares system RAM

    @property
    def vram_gb(self) -> float:
        """Memory of the biggest dedicated GPU (0 if none)."""
        return max((g.vram_gb for g in self.gpus), default=0.0)

    @property
    def best_gpu(self) -> GPU | None:
        """The GPU with the most memory, if any."""
        return max(self.gpus, key=lambda g: g.vram_gb, default=None)

    def summary(self) -> str:
        """One human-readable line, e.g. '32 GB RAM · RTX 4060 (8 GB) · 24 threads'."""
        parts = [f"{self.ram_gb:.0f} GB RAM"]
        gpu = self.best_gpu
        if self.unified_memory:
            parts.append("Apple silicon (shared memory)")
        elif gpu and gpu.vram_gb >= 1:
            parts.append(f"{_short_gpu_name(gpu.name)} ({gpu.vram_gb:.0f} GB)")
        else:
            parts.append("no dedicated GPU")
        parts.append(f"{self.cpu_threads} threads")
        return " · ".join(parts)


def detect_hardware(models_dir: Path | None = None) -> HardwareInfo:
    """Probe the machine.

    Args:
        models_dir: Where Ollama stores models; free space is measured there
            (defaults to the Ollama models folder, or the home directory).
    """
    system = platform.system()
    apple_silicon = system == "Darwin" and platform.machine() == "arm64"
    gpus = _detect_gpus(system)
    if apple_silicon:
        gpus = (GPU("Apple silicon", 0.0, "apple"),)
    info = HardwareInfo(
        os=system,
        ram_gb=round(_total_ram_bytes(system) / _GIB, 1),
        cpu_threads=os.cpu_count() or 1,
        free_disk_gb=round(_free_disk_bytes(models_dir or ollama_models_dir()) / _GIB, 1),
        gpus=gpus,
        unified_memory=apple_silicon,
    )
    logger.info("Detected hardware: %s, %.0f GB free disk", info.summary(), info.free_disk_gb)
    return info


def ollama_models_dir() -> Path:
    """Folder Ollama downloads models into (respects ``OLLAMA_MODELS``)."""
    custom = os.environ.get("OLLAMA_MODELS")
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".ollama" / "models"


# ---------------------------------------------------------------------------
# RAM
# ---------------------------------------------------------------------------

def _total_ram_bytes(system: str) -> int:
    try:
        if system == "Linux":
            return _linux_ram()
        if system == "Windows":
            return _windows_ram()
        if system == "Darwin":
            return int(_run(["sysctl", "-n", "hw.memsize"]) or 0)
    except Exception as exc:
        logger.warning("RAM detection failed: %s", exc)
    return 0


def _linux_ram() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    return 0


def _windows_ram() -> int:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
    return int(status.ullTotalPhys)


# ---------------------------------------------------------------------------
# GPUs
# ---------------------------------------------------------------------------

def _detect_gpus(system: str) -> tuple[GPU, ...]:
    """NVIDIA via nvidia-smi everywhere; AMD/Intel via sysfs or the registry."""
    gpus: list[GPU] = []
    try:
        gpus.extend(_nvidia_gpus())
        if system == "Linux":
            gpus.extend(_linux_amd_gpus())
        elif system == "Windows" and not gpus:
            gpus.extend(_windows_registry_gpus())
    except Exception as exc:
        logger.warning("GPU detection failed: %s", exc)
    return tuple(gpus)


def _nvidia_gpus() -> list[GPU]:
    out = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
    )
    return parse_nvidia_smi(out) if out else []


def parse_nvidia_smi(output: str) -> list[GPU]:
    """Parse ``name, MiB`` lines from nvidia-smi."""
    gpus = []
    for line in output.strip().splitlines():
        name, _, mib = line.rpartition(",")
        try:
            gpus.append(GPU(name.strip(), round(float(mib) / 1024, 1), "nvidia"))
        except ValueError:
            continue
    return gpus


def _linux_amd_gpus(drm: Path = Path("/sys/class/drm")) -> list[GPU]:
    """Dedicated AMD cards expose their VRAM size in sysfs (amdgpu driver)."""
    gpus = []
    for vram_file in sorted(drm.glob("card[0-9]*/device/mem_info_vram_total")):
        try:
            vram = int(vram_file.read_text().strip()) / _GIB
        except (OSError, ValueError):
            continue
        if vram >= 1:  # integrated APUs report a small carve-out; skip them
            gpus.append(GPU("AMD Radeon", round(vram, 1), "amd"))
    return gpus


def _windows_registry_gpus() -> list[GPU]:
    """Read adapter memory from the display-class registry keys (read-only)."""
    import winreg  # Windows-only module

    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    gpus = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                with winreg.OpenKey(root, winreg.EnumKey(root, i)) as key:
                    name = winreg.QueryValueEx(key, "DriverDesc")[0]
                    size = winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")[0]
            except OSError:
                continue
            vram = int(size) / _GIB if isinstance(size, int) else 0
            if vram >= 1:
                gpus.append(GPU(name, round(vram, 1), _vendor(name)))
    return gpus


def _vendor(name: str) -> str:
    lowered = name.lower()
    for vendor, marks in (("nvidia", ("nvidia", "geforce", "rtx")), ("amd", ("amd", "radeon")), ("intel", ("intel", "arc"))):
        if any(m in lowered for m in marks):
            return vendor
    return "other"


def _short_gpu_name(name: str) -> str:
    """'NVIDIA GeForce RTX 4060 Laptop GPU' → 'RTX 4060 Laptop'."""
    for prefix in ("NVIDIA ", "GeForce ", "AMD "):
        name = name.replace(prefix, "")
    return name.replace(" GPU", "").strip()


# ---------------------------------------------------------------------------
# Disk / helpers
# ---------------------------------------------------------------------------

def _free_disk_bytes(path: Path) -> int:
    """Free space on the drive holding *path* (walks up to an existing folder)."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError as exc:
        logger.warning("Disk detection failed: %s", exc)
        return 0


def _run(cmd: list[str]) -> str:
    """Run a probe command; return stdout or '' if it's missing or fails."""
    if shutil.which(cmd[0]) is None:
        return ""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""
