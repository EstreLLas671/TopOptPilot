"""Startup-safe inventories for the human-controlled engineering environment."""

from __future__ import annotations

import os
import json
import platform
import threading
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

from topoptpilot_desktop.engineering.matlab import MatlabInstallation, discover_matlab_installations, probe_matlab_installation
from topoptpilot_desktop.engineering.runtime_discovery import RuntimeInstallation, runtime_inventory


def _discover_matlab() -> list[MatlabInstallation]:
    configured = os.environ.get("TOPOPTPILOT_MATLAB_PATH")
    if configured:
        return discover_matlab_installations(configured_path=configured)
    return discover_matlab_installations()


class MatlabInventory:
    """Thread-safe, lazily initialized MATLAB installation inventory."""

    def __init__(
        self,
        *,
        discover: Callable[[], list[MatlabInstallation]] = _discover_matlab,
    ) -> None:
        self._discover = discover
        self._installations: list[MatlabInstallation] = []
        self._initialized = False
        self._lock = threading.RLock()

    @property
    def initialized(self) -> bool:
        with self._lock:
            return self._initialized

    def refresh(self) -> list[MatlabInstallation]:
        installations = self._discover()
        with self._lock:
            self._installations = list(installations)
            self._initialized = True
            return list(self._installations)

    def snapshot(self) -> list[MatlabInstallation]:
        with self._lock:
            initialized = self._initialized
        if not initialized:
            return self.refresh()
        with self._lock:
            return list(self._installations)



matlab_inventory = MatlabInventory()


def _cache_path() -> Path:
    configured = os.environ.get("TOPPILOT_ENVIRONMENT_CACHE")
    if configured:
        return Path(configured).expanduser()
    base = Path(os.environ.get("TOPOPTPILOT_DATA_DIR") or os.environ.get("TOPPILOT_DATA_DIR") or (Path.home() / "AppData/Local/TopOptPilot"))
    return base / "environment.json"


_environment_lock = threading.RLock()
_environment_cache: dict[str, object] | None = None
_environment_cache_file: str | None = None


def _read_environment_cache() -> dict[str, object] | None:
    global _environment_cache, _environment_cache_file
    cache_file = str(_cache_path().resolve())
    with _environment_lock:
        value = dict(_environment_cache) if _environment_cache is not None and _environment_cache_file == cache_file else None
    if value is None:
        try:
            value = json.loads(_cache_path().read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
    if not isinstance(value, dict) or not isinstance(value.get("matlab"), dict):
        return None
    executable = value["matlab"].get("path")
    if not isinstance(executable, str) or not executable or not os.path.isfile(executable):
        return None
    with _environment_lock:
        _environment_cache = dict(value)
        _environment_cache_file = cache_file
    return dict(value)


def _write_environment_cache(value: dict[str, object]) -> None:
    global _environment_cache, _environment_cache_file
    target = _cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    with _environment_lock:
        _environment_cache = dict(value)


def cached_environment() -> dict[str, object] | None:
    return _read_environment_cache()


def invalidate_environment_cache() -> None:
    global _environment_cache, _environment_cache_file
    with _environment_lock:
        _environment_cache = None
        _environment_cache_file = None


async def discover_environment(*, force: bool = False) -> dict[str, object]:
    if not force:
        cached = _read_environment_cache()
        if cached is not None:
            cached["cached"] = True
            return cached
    installations = matlab_inventory.refresh()
    selected: MatlabInstallation | None = None
    diagnostic = "未检测到可启动的 MATLAB。"
    for candidate in installations:
        result = await probe_matlab_installation(candidate)
        candidate.probe_state = "ready" if result.usable else "failed"
        candidate.diagnostic = result.diagnostic
        diagnostic = result.diagnostic
        if result.usable:
            selected = candidate
            candidate.version = result.version or candidate.version
            break
    runtime = runtime_inventory.snapshot()
    value: dict[str, object] = {
        "cached": False,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "matlab": {"path": selected.executable if selected else "", "release": selected.release if selected else "", "version": selected.version if selected else "", "probeState": "ready" if selected else ("failed" if installations else "unknown"), "diagnostic": diagnostic},
        "python": {"mode": "packaged" if getattr(__import__("sys"), "frozen", False) else "source", "version": platform.python_version()},
        "runtime": {"state": "ready" if any(item.usable for item in runtime) else "optional", "count": len(runtime)},
    }
    _write_environment_cache(value)
    return value


def initialize_engineering_discovery() -> dict[str, list[MatlabInstallation] | list[RuntimeInstallation]]:
    """Refresh both inventories without launching MATLAB or a Runtime binary."""
    return {
        "matlab": matlab_inventory.refresh(),
        "runtime": runtime_inventory.refresh(),
    }
