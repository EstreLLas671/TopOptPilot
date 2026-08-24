"""Startup-safe inventories for the human-controlled engineering environment."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

from idesktop_v2.engineering.matlab import MatlabInstallation, discover_matlab_installations
from idesktop_v2.engineering.runtime_discovery import RuntimeInstallation, runtime_inventory


def _discover_matlab() -> list[MatlabInstallation]:
    configured = os.environ.get("IDESKTOP_MATLAB_PATH")
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


def initialize_engineering_discovery() -> dict[str, list[MatlabInstallation] | list[RuntimeInstallation]]:
    """Refresh both inventories without launching MATLAB or a Runtime binary."""
    return {
        "matlab": matlab_inventory.refresh(),
        "runtime": runtime_inventory.refresh(),
    }
