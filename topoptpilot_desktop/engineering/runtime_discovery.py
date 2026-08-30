"""Read-only discovery of installed Windows MATLAB Runtime distributions."""

from __future__ import annotations

import os
import re
import threading
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_RELEASE_RE = re.compile(r"R20\d{2}[ab]", re.IGNORECASE)
_VERSION_DIR_RE = re.compile(r"(?:R20\d{2}[ab]|v\d+)", re.IGNORECASE)
_DLL_RE = re.compile(r"mclmcrrt(?P<major>\d+)_(?P<minor>\d+)\.dll", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RuntimeInstallation:
    release: str
    version: str
    path: Path
    source: str
    usable: bool
    reason: str
    dll_path: Path | None = None
    uninstaller_path: Path | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "release": self.release,
            "version": self.version,
            "path": str(self.path),
            "source": self.source,
            "usable": self.usable,
            "reason": self.reason,
            "dllPath": str(self.dll_path) if self.dll_path else None,
            "uninstallerPath": str(self.uninstaller_path) if self.uninstaller_path else None,
        }


def _release_from(value: str) -> str:
    match = _RELEASE_RE.search(value)
    if not match:
        return ""
    release = match.group(0)
    return release[:5].upper() + release[5].lower()


def _version_info(root: Path) -> tuple[str, str]:
    path = root / "VersionInfo.xml"
    try:
        document = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return _release_from(str(root)), ""

    def value(name: str) -> str:
        node = next((item for item in document.iter() if item.tag.rsplit("}", 1)[-1].lower() == name), None)
        return (node.text or "").strip() if node is not None else ""

    return value("release") or _release_from(str(root)), value("version")


def _runtime_dll(root: Path) -> Path | None:
    for directory in (root / "runtime" / "win64", root / "bin" / "win64"):
        try:
            candidates = sorted(
                (item.resolve() for item in directory.iterdir()
                 if item.is_file() and item.name.lower().startswith("mclmcrrt") and item.suffix.lower() == ".dll"),
                key=lambda item: item.name.lower(),
            )
        except OSError:
            continue
        if candidates:
            return candidates[0]
    return None


def _version_from_dll(dll_path: Path | None) -> str:
    if dll_path is None:
        return ""
    match = _DLL_RE.fullmatch(dll_path.name)
    return f"{match.group('major')}.{match.group('minor')}" if match else ""


def _inspect_runtime(root: Path, *, source: str, release_hint: str = "", version_hint: str = "") -> RuntimeInstallation:
    try:
        resolved = root.expanduser().resolve(strict=False)
    except OSError:
        resolved = root.expanduser().absolute()
    release, version = _version_info(resolved)
    release = release or release_hint or _release_from(str(resolved))
    matlab_executable = resolved / "bin" / "matlab.exe"
    dll_path = _runtime_dll(resolved)
    uninstaller = resolved / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe"
    uninstaller_path = uninstaller.resolve() if uninstaller.is_file() else None
    version = version or version_hint or _version_from_dll(dll_path)

    if matlab_executable.is_file():
        usable = False
        reason = "检测到完整 MATLAB，不能作为独立 MATLAB Runtime"
    elif dll_path is None and uninstaller_path is None:
        usable = False
        reason = "缺少 MATLAB Runtime DLL 和卸载程序"
    elif dll_path is None:
        usable = False
        reason = "缺少 mclmcrrt Runtime DLL"
    elif uninstaller_path is None:
        usable = False
        reason = "缺少 MATLAB Runtime 卸载程序"
    else:
        usable = True
        reason = "MATLAB Runtime 安装完整"
    return RuntimeInstallation(
        release=release,
        version=version,
        path=resolved,
        source=source,
        usable=usable,
        reason=reason,
        dll_path=dll_path,
        uninstaller_path=uninstaller_path,
    )


def _system_runtime_registry_roots() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []

    roots: list[dict[str, str]] = []
    key_names = (
        r"SOFTWARE\MathWorks\MATLAB Runtime",
        r"SOFTWARE\MathWorks\MATLAB Compiler Runtime",
    )
    views = tuple(dict.fromkeys((0, getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0))))

    def walk(key: Any, key_path: str, depth: int) -> None:
        if depth > 5:
            return
        release_hint = _release_from(key_path)
        index = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, index)
            except OSError:
                break
            index += 1
            if not isinstance(value, str) or name.lower() not in {
                "matlabroot", "installpath", "installationfolder", "path", "root",
            }:
                continue
            candidate = value.strip().strip('"')
            if candidate:
                roots.append({"root": candidate, "release": release_hint})
        child_index = 0
        while True:
            try:
                child_name = winreg.EnumKey(key, child_index)
            except OSError:
                break
            child_index += 1
            try:
                child = winreg.OpenKey(key, child_name, 0, winreg.KEY_READ)
            except OSError:
                continue
            try:
                walk(child, f"{key_path}\\{child_name}", depth + 1)
            finally:
                winreg.CloseKey(child)

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for key_name in key_names:
            for view in views:
                try:
                    key = winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                try:
                    walk(key, key_name, 0)
                finally:
                    winreg.CloseKey(key)
    return roots


def _standard_runtime_bases() -> list[Path]:
    values: list[Path] = [Path(r"C:\Program Files\MATLAB\MATLAB Runtime")]
    for name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(name)
        if base:
            values.append(Path(base) / "MATLAB" / "MATLAB Runtime")
    unique: list[Path] = []
    seen: set[str] = set()
    for value in values:
        key = os.path.normcase(str(value))
        if key not in seen:
            seen.add(key)
            unique.append(value)
    return unique


def _standard_candidates(bases: Iterable[str | Path]) -> list[Path]:
    candidates: list[Path] = []
    for raw_base in bases:
        base = Path(raw_base).expanduser()
        try:
            resolved_base = base.resolve(strict=True)
            children = list(resolved_base.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or not _VERSION_DIR_RE.fullmatch(child.name):
                continue
            try:
                resolved_child = child.resolve(strict=True)
            except OSError:
                continue
            if resolved_child.parent != resolved_base:
                continue
            if _runtime_dll(resolved_child) is None:
                nested = resolved_child / child.name
                try:
                    resolved_nested = nested.resolve(strict=True)
                except OSError:
                    resolved_nested = None
                if (
                    resolved_nested is not None
                    and resolved_nested.parent == resolved_child
                    and _runtime_dll(resolved_nested) is not None
                    and (resolved_nested / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe").is_file()
                ):
                    resolved_child = resolved_nested
            candidates.append(resolved_child)
    return candidates


def discover_installed_runtimes(
    *,
    registry_roots: list[dict[str, str]] | None = None,
    standard_bases: list[str | Path] | None = None,
) -> list[RuntimeInstallation]:
    """Find candidates without executing any discovered binary."""
    candidates: list[tuple[str, Path, str, str]] = []
    for entry in registry_roots if registry_roots is not None else _system_runtime_registry_roots():
        raw_root = entry.get("root", "").strip()
        if raw_root:
            candidates.append(("registry", Path(raw_root), entry.get("release", ""), entry.get("version", "")))
    bases = standard_bases if standard_bases is not None else _standard_runtime_bases()
    candidates.extend(("standard", path, "", "") for path in _standard_candidates(bases))

    installations: list[RuntimeInstallation] = []
    seen: set[str] = set()
    for source, root, release_hint, version_hint in candidates:
        try:
            key = os.path.normcase(str(root.expanduser().resolve(strict=False)))
        except OSError:
            key = os.path.normcase(str(root.expanduser().absolute()))
        if key in seen:
            continue
        seen.add(key)
        installations.append(
            _inspect_runtime(root, source=source, release_hint=release_hint, version_hint=version_hint)
        )
    return installations


class RuntimeInventory:
    """Thread-safe cache shared by startup, health, and discovery routes."""

    def __init__(self, *, discover: Callable[[], list[RuntimeInstallation]] = discover_installed_runtimes) -> None:
        self._discover = discover
        self._installations: list[RuntimeInstallation] = []
        self._initialized = False
        self._lock = threading.RLock()

    @property
    def initialized(self) -> bool:
        with self._lock:
            return self._initialized

    def refresh(self) -> list[RuntimeInstallation]:
        installations = self._discover()
        with self._lock:
            self._installations = list(installations)
            self._initialized = True
            return list(self._installations)

    def snapshot(self) -> list[RuntimeInstallation]:
        with self._lock:
            initialized = self._initialized
        if not initialized:
            return self.refresh()
        with self._lock:
            return list(self._installations)


runtime_inventory = RuntimeInventory()


def initialize_runtime_discovery() -> list[RuntimeInstallation]:
    """Startup hook kept callable for sidecar health reinitialization."""
    return runtime_inventory.refresh()
