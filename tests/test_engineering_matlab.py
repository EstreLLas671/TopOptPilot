from __future__ import annotations

import asyncio
import subprocess
import threading
from pathlib import Path

from topoptpilot_desktop.engineering import matlab as matlab_module
from topoptpilot_desktop.engineering.matlab import (
    MatlabInstallation,
    classify_runtime_root,
    discover_matlab_installations,
    probe_matlab_installation,
)


def test_discovery_deduplicates_registry_standard_and_path_candidates() -> None:
    roots = [r"C:\Program Files\MATLAB\R2025b"]
    executable = r"C:\Program Files\MATLAB\R2025b\bin\matlab.exe"

    installations = discover_matlab_installations(
        configured_path=r"C:\Program Files\MATLAB\R2025b\bin\matlab.exe",
        registry_roots=[{"release": "R2025b", "root": roots[0]}],
        standard_roots=roots,
        where_executables=[executable],
        path_value=r"C:\Program Files\MATLAB\R2025b\bin",
        file_exists=lambda value: value.lower() == executable.lower(),
        read_version_info=lambda _: {"release": "R2025b", "version": "25.2.0"},
    )

    assert len(installations) == 1
    assert installations[0].source == "settings"
    assert installations[0].release == "R2025b"
    assert installations[0].version == "25.2.0"


def test_discovery_excludes_missing_matlab_executables() -> None:
    installations = discover_matlab_installations(
        standard_roots=[r"D:\MATLAB\R2025b"],
        file_exists=lambda _: False,
    )

    assert installations == []


def test_runtime_classification_rejects_nested_release_and_accepts_complete_runtime() -> None:
    ready_root = r"D:\MATLAB Runtime\R2025b"
    nested_root = r"D:\MATLAB Runtime\R2025b\R2025b"
    files = {
        r"D:\MATLAB Runtime\R2025b\runtime\win64\mclmcrrt25_2.dll".lower(),
        r"D:\MATLAB Runtime\R2025b\bin\win64\Uninstall_MATLAB_Runtime.exe".lower(),
        r"D:\MATLAB Runtime\R2025b\R2025b\runtime\win64\mclmcrrt25_2.dll".lower(),
    }

    status = classify_runtime_root(ready_root, file_exists=lambda p: p.lower() in files)
    nested = classify_runtime_root(nested_root, file_exists=lambda p: p.lower() in files)

    assert status.state == "ready"
    assert status.dll_path and status.dll_path.lower().endswith("mclmcrrt25_2.dll")
    assert nested.state == "nested"


def test_probe_requires_marker_handshake_and_maps_failure_to_infrastructure_error() -> None:
    installation = MatlabInstallation(
        release="R2025b",
        version="",
        executable=r"C:\MATLAB\R2025b\bin\matlab.exe",
        source="settings",
    )

    def failed_runner(_executable: str, _args: list[str], _timeout: float) -> tuple[int | None, str]:
        return 1, "File system inconsistency"

    result = asyncio.run(
        probe_matlab_installation(
            installation,
            runner=failed_runner,
            marker_factory=lambda: ("BEGIN", "END"),
        )
    )

    assert result.usable is False
    assert result.error.code == "MATLAB_INFRASTRUCTURE"
    assert result.error.source == "matlab"


def test_probe_accepts_only_a_complete_batch_marker_transcript() -> None:
    installation = MatlabInstallation(
        release="R2025b",
        version="",
        executable=r"C:\MATLAB\R2025b\bin\matlab.exe",
        source="settings",
    )

    def good_runner(_executable: str, args: list[str], _timeout: float) -> tuple[int | None, str]:
        assert args[:2] == ["-wait", "-batch"]
        return 0, "BEGIN\n5\nVERSION=25.2.0\nEND\n"

    result = asyncio.run(
        probe_matlab_installation(
            installation,
            runner=good_runner,
            marker_factory=lambda: ("BEGIN", "END"),
        )
    )

    assert result.usable is True
    assert result.version == "25.2.0"
    assert result.error is None

def test_default_probe_timeout_terminates_matlab_process_tree(monkeypatch) -> None:
    terminated: list[int] = []

    class BlockingStdout:
        def __init__(self) -> None:
            self.closed = threading.Event()

        def __iter__(self):
            return self

        def __next__(self):
            self.closed.wait()
            raise StopIteration

        def close(self) -> None:
            self.closed.set()

    class TimeoutProcess:
        pid = 4242
        returncode = None
        stdout = BlockingStdout()

        def poll(self):
            return None

    process = TimeoutProcess()
    monkeypatch.setattr(matlab_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(matlab_module, "_terminate_process_tree", lambda value: terminated.append(value.pid))
    installation = MatlabInstallation("R2024b", "", r"C:\MATLAB\bin\matlab.exe", "settings")

    result = asyncio.run(probe_matlab_installation(installation, timeout_seconds=0.01))

    assert result.usable is False
    assert "timed out" in result.diagnostic
    assert terminated == [4242]

def test_default_probe_accepts_complete_stream_before_process_exit(monkeypatch) -> None:
    terminated: list[int] = []

    class MarkerStream:
        def __init__(self) -> None:
            self.lines = iter([
                "TOPOPTPILOT_MATLAB_BEGIN\n",
                "5\n",
                "VERSION=24.2.0.2712019 (R2024b)\n",
                "TOPOPTPILOT_MATLAB_END\n",
            ])

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.lines)

        def close(self) -> None:
            pass

    class RunningProcess:
        pid = 4343
        returncode = None
        stdout = MarkerStream()

        def poll(self):
            return None

    process = RunningProcess()
    monkeypatch.setattr(matlab_module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(matlab_module, "_terminate_process_tree", lambda value: terminated.append(value.pid))
    installation = MatlabInstallation("R2024b", "", r"C:\MATLAB\bin\matlab.exe", "settings")

    result = asyncio.run(probe_matlab_installation(installation))

    assert result.usable is True
    assert result.version == "24.2.0.2712019 (R2024b)"
    assert "complete handshake" in result.diagnostic
    assert terminated == [4343]
