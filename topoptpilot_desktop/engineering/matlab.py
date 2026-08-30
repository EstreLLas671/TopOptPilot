"""Safe MATLAB discovery and probe helpers for the human-controlled lane."""

from __future__ import annotations

import asyncio
import inspect
import queue
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from typing import Any, Callable

from topoptpilot_desktop.artifacts.models import ErrorEnvelope, ErrorSource
from topoptpilot_desktop.engineering.matlab_runner import _terminate_process_tree


_DISCOVERY_SOURCES = {"settings", "registry", "standard", "path", "where"}
_RELEASE_RE = re.compile(r"(?:^|[\\/])(R20\d{2}[ab])(?:[\\/]|$)", re.IGNORECASE)
_DLL_RE = re.compile(r"^mclmcrrt\d+_\d+\.dll$", re.IGNORECASE)


@dataclass(slots=True)
class MatlabInstallation:
    release: str
    version: str
    executable: str
    source: str
    probe_state: str = "unknown"
    diagnostic: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "release": self.release,
            "version": self.version,
            "executable": self.executable,
            "source": self.source,
            "probeState": self.probe_state,
            "diagnostic": self.diagnostic,
        }


@dataclass(slots=True)
class RuntimeRootStatus:
    state: str
    root: str
    dll_path: str | None = None
    uninstaller_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "root": self.root,
            "dllPath": self.dll_path,
            "uninstallerPath": self.uninstaller_path,
        }


@dataclass(slots=True)
class MatlabProbeResult:
    usable: bool
    launch_mode: str | None = None
    version: str | None = None
    diagnostic: str = ""
    error: ErrorEnvelope | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "usable": self.usable,
            "launchMode": self.launch_mode,
            "version": self.version,
            "diagnostic": self.diagnostic,
        }
        if self.error is not None:
            data["error"] = self.error.model_dump(mode="json", by_alias=True)
        return data


def _release_from_path(value: str) -> str:
    match = _RELEASE_RE.search(value)
    return match.group(1) if match else ""


def _matlab_executable(value: str) -> str:
    normalized = value.strip().strip('"')
    if normalized.lower().endswith("matlab.exe"):
        return str(PureWindowsPath(normalized))
    if normalized.lower().endswith("\\bin"):
        return str(PureWindowsPath(normalized) / "matlab.exe")
    return str(PureWindowsPath(normalized) / "bin" / "matlab.exe")


def _default_version_info(root: str) -> dict[str, str] | None:
    try:
        text = open(str(PureWindowsPath(root) / "VersionInfo.xml"), encoding="utf-8").read()
    except (OSError, UnicodeError):
        return None
    release = re.search(r"<release>\s*([^<]+)\s*</release>", text, re.IGNORECASE)
    version = re.search(r"<version>\s*([^<]+)\s*</version>", text, re.IGNORECASE)
    return {
        "release": release.group(1).strip() if release else _release_from_path(root),
        "version": version.group(1).strip() if version else "",
    }


def _system_registry_roots() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(
            ["reg.exe", "query", r"HKLM\SOFTWARE\MathWorks\MATLAB", "/s", "/v", "MATLABROOT"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return []
    roots: list[dict[str, str]] = []
    release = ""
    for raw in completed.stdout.splitlines():
        line = raw.strip()
        match = re.search(r"\\MATLAB\\(R20\d{2}[ab])$", line, re.IGNORECASE)
        if match:
            release = match.group(1)
        root_match = re.match(r"MATLABROOT\s+REG_\w+\s+(.+)$", line, re.IGNORECASE)
        if root_match:
            root = root_match.group(1).strip()
            roots.append({"release": release or _release_from_path(root), "root": root})
    return roots


def _where_executables() -> list[str]:
    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(
            ["where.exe", "matlab.exe"], capture_output=True, text=True, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def discover_matlab_installations(
    *,
    configured_path: str | None = None,
    registry_roots: list[dict[str, str]] | None = None,
    standard_roots: list[str] | None = None,
    path_value: str | None = None,
    where_executables: list[str] | None = None,
    file_exists: Callable[[str], bool] = os.path.isfile,
    read_version_info: Callable[[str], dict[str, str] | None] = _default_version_info,
) -> list[MatlabInstallation]:
    candidates: list[tuple[str, str, str]] = []
    if configured_path:
        candidates.append(("settings", "", configured_path))
    for entry in registry_roots if registry_roots is not None else _system_registry_roots():
        candidates.append(("registry", entry.get("release", ""), entry["root"]))
    if standard_roots is None:
        program_files = [os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles")]
        standard_roots = []
        for base in dict.fromkeys(value for value in program_files if value):
            matlab_dir = str(PureWindowsPath(base) / "MATLAB")
            try:
                standard_roots.extend(
                    str(PureWindowsPath(matlab_dir) / entry.name)
                    for entry in os.scandir(matlab_dir)
                    if entry.is_dir() and re.fullmatch(r"R20\d{2}[ab]", entry.name, re.IGNORECASE)
                )
            except OSError:
                pass
    for root in standard_roots:
        candidates.append(("standard", _release_from_path(root), root))
    for executable in where_executables if where_executables is not None else _where_executables():
        candidates.append(("where", _release_from_path(executable), executable))
    for entry in (path_value if path_value is not None else os.environ.get("PATH", "")).split(";"):
        if entry:
            candidates.append(("path", _release_from_path(entry), entry))

    seen: set[str] = set()
    installations: list[MatlabInstallation] = []
    for source, release, candidate in candidates:
        executable = _matlab_executable(candidate)
        key = executable.lower()
        if key in seen or not file_exists(executable):
            continue
        seen.add(key)
        root = str(PureWindowsPath(executable).parent.parent)
        info = read_version_info(root) or {}
        installations.append(MatlabInstallation(
            release=info.get("release") or release or _release_from_path(executable),
            version=info.get("version", ""), executable=executable, source=source,
        ))
    return installations


def _runtime_dll(root: str, file_exists: Callable[[str], bool]) -> str | None:
    for relative in (PureWindowsPath("runtime") / "win64", PureWindowsPath("bin") / "win64"):
        directory = str(PureWindowsPath(root) / relative)
        try:
            for entry in os.scandir(directory):
                if entry.is_file() and _DLL_RE.fullmatch(entry.name) and file_exists(entry.path):
                    return str(PureWindowsPath(entry.path))
        except OSError:
            continue
    # Test doubles and packaged layouts may expose existence without directory iteration.
    for name in ("mclmcrrt25_2.dll", "mclmcrrt.dll"):
        for relative in (PureWindowsPath("runtime") / "win64", PureWindowsPath("bin") / "win64"):
            candidate = str(PureWindowsPath(root) / relative / name)
            if file_exists(candidate):
                return candidate
    return None


def classify_runtime_root(root: str, *, file_exists: Callable[[str], bool] = os.path.isfile) -> RuntimeRootStatus:
    normalized = str(PureWindowsPath(root))
    dll_path = _runtime_dll(normalized, file_exists)
    uninstaller = str(PureWindowsPath(normalized) / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe")
    base = PureWindowsPath(normalized).name.lower()
    parent = PureWindowsPath(normalized).parent.name.lower()
    if dll_path and file_exists(uninstaller):
        return RuntimeRootStatus("ready", root, dll_path, uninstaller)
    if dll_path and re.fullmatch(r"R20\d{2}[ab]", base, re.IGNORECASE) and base == parent:
        return RuntimeRootStatus("nested", root, dll_path, uninstaller)
    return RuntimeRootStatus("missing", root)


def _probe_error(message: str, details: dict[str, Any] | None = None) -> ErrorEnvelope:
    return ErrorEnvelope(code="MATLAB_INFRASTRUCTURE", source=ErrorSource.MATLAB, message=message, retryable=True, details=details)


def _parse_probe(transcript: str, begin: str, end: str) -> str | None:
    lines = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", transcript).splitlines()
    lines = [line.strip() for line in lines]
    try:
        start = lines.index(begin)
        finish = lines.index(end, start + 1)
    except ValueError:
        return None
    body = [line for line in lines[start + 1:finish] if line]
    if "5" not in body:
        return None
    version = next((line.removeprefix("VERSION=").strip() for line in body if line.startswith("VERSION=")), None)
    return version or None


def _read_probe_output(process: subprocess.Popen[str], output: queue.Queue[str | None]) -> None:
    try:
        if process.stdout is not None:
            for line in process.stdout:
                output.put(line)
    except (OSError, ValueError):
        pass
    finally:
        output.put(None)


def _run_matlab_probe_process(
    executable: str, command: list[str], timeout: float, end_marker: str
) -> tuple[int | None, str]:
    try:
        process = subprocess.Popen(
            [executable, *command], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return None, str(exc)
    output: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_read_probe_output, args=(process, output), daemon=True)
    reader.start()
    transcript: list[str] = []
    deadline = time.monotonic() + timeout
    stream_finished = False
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            line = output.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue
        if line is None:
            stream_finished = True
            break
        transcript.append(line)
        if line.strip() == end_marker:
            _terminate_process_tree(process)
            if process.stdout is not None:
                process.stdout.close()
            reader.join(timeout=1)
            transcript.append("[probe cleanup: process tree terminated after complete handshake]\n")
            return 0, "".join(transcript)
    if stream_finished:
        try:
            return process.wait(timeout=1), "".join(transcript)
        except subprocess.TimeoutExpired:
            pass
    _terminate_process_tree(process)
    if process.stdout is not None:
        process.stdout.close()
    reader.join(timeout=1)
    while True:
        try:
            line = output.get_nowait()
        except queue.Empty:
            break
        if line is not None:
            transcript.append(line)
    return None, f"MATLAB probe timed out after {timeout:.1f} seconds\n{''.join(transcript)}".strip()

async def probe_matlab_installation(
    installation: MatlabInstallation,
    *,
    runner: Callable[[str, list[str], float], Any] | None = None,
    marker_factory: Callable[[], tuple[str, str]] | None = None,
    timeout_seconds: float = 120.0,
) -> MatlabProbeResult:
    begin, end = (marker_factory or (lambda: ("TOPOPTPILOT_MATLAB_BEGIN", "TOPOPTPILOT_MATLAB_END")))()
    expression = (
        f"fprintf(1,'{begin}\\n'); fprintf(1,'%.0f\\n',2+3); "
        f"fprintf(1,'VERSION=%s\\n',version); fprintf(1,'{end}\\n');"
    )
    args = ["-wait", "-batch", expression]
    if runner is None:
        async def default_runner(executable: str, command: list[str], timeout: float) -> tuple[int | None, str]:
            return await asyncio.to_thread(_run_matlab_probe_process, executable, command, timeout, end)
        runner = default_runner
    try:
        result = runner(installation.executable, args, timeout_seconds)
        if inspect.isawaitable(result):
            result = await result
        exit_code, transcript = result
    except Exception as exc:  # probe is an infrastructure boundary
        exit_code, transcript = None, str(exc)
    version = _parse_probe(transcript, begin, end) if exit_code == 0 else None
    if version:
        return MatlabProbeResult(True, "batch", version, f"batch exit=0: {transcript[-4000:].strip()}")
    error = _probe_error("MATLAB probe did not complete the required batch handshake.", {"exitCode": exit_code, "transcript": transcript[-4000:]})
    return MatlabProbeResult(False, diagnostic=f"batch exit={exit_code if exit_code is not None else 'launch-error'}: {transcript[-4000:].strip() or '(无输出)'}", error=error)