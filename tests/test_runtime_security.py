from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from topoptpilot_desktop.engineering.matlab_runner import (
    MatlabInfrastructureError,
    build_runtime_environment,
    run_runtime_solver,
)
from topoptpilot_desktop.engineering.runtime_profiles import (
    RuntimeProfileError,
    RuntimeProfileStore,
    stage_runtime_solver,
)


def _runtime_layout(root: Path) -> Path:
    dll = root / "runtime" / "win64" / "mclmcrrt25_2.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"runtime-dll")
    uninstaller = root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe"
    uninstaller.parent.mkdir(parents=True)
    uninstaller.write_bytes(b"uninstaller")
    return dll


def _solver(path: Path, payload: bytes = b"solver-v1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def test_profile_rejects_arbitrary_exe_and_accepts_explicit_allowlist(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    solver = _solver(tmp_path / "downloads" / "arbitrary.exe")

    with pytest.raises(RuntimeProfileError, match="可信"):
        RuntimeProfileStore(environ={}).verify(runtime_root, solver)

    by_file = RuntimeProfileStore(
        environ={"TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST": str(solver)}
    ).verify(runtime_root, solver)
    by_root = RuntimeProfileStore(
        environ={"TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST": str(solver.parent)}
    ).verify(runtime_root, solver)
    assert by_file.solver_executable == solver.resolve()
    assert by_root.solver_executable == solver.resolve()


def test_profile_accepts_only_explicit_solver_subdirectories_under_resource_root(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    resource_root = tmp_path / "resources"
    trusted = _solver(resource_root / "solver" / "TopOptSolver.exe")
    backend = _solver(resource_root / "bin" / "topoptpilot-backend.exe")

    store = RuntimeProfileStore(environ={"TOPPILOT_RESOURCE_ROOT": str(resource_root)})
    assert store.verify(runtime_root, trusted).usable
    with pytest.raises(RuntimeProfileError, match="可信"):
        store.verify(runtime_root, backend)


def test_headless_solver_must_also_be_allowlisted(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    solver = _solver(tmp_path / "external" / "TopOptSolver.exe")
    configured = {
        "TOPOPTPILOT_RUNTIME_ROOT": str(runtime_root),
        "TOPOPTPILOT_RUNTIME_SOLVER": str(solver),
    }
    with pytest.raises(RuntimeProfileError, match="可信"):
        RuntimeProfileStore(environ=configured).verify_environment()

    configured["TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST"] = str(solver)
    assert RuntimeProfileStore(environ=configured).verify_environment().usable


def test_profile_prunes_expired_entries_and_bounds_capacity(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    solver = _solver(tmp_path / "trusted" / "TopOptSolver.exe")
    now = [0.0]
    store = RuntimeProfileStore(
        ttl_seconds=2.0,
        max_profiles=2,
        clock=lambda: now[0],
        environ={"TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST": str(solver)},
    )
    expired = store.verify(runtime_root, solver)
    now[0] = 3.0
    store.verify(runtime_root, solver)
    assert store.profile_count == 1
    with pytest.raises(RuntimeProfileError, match="不存在|过期"):
        store.resolve(expired.profile_id)

    store.verify(runtime_root, solver)
    with pytest.raises(RuntimeProfileError, match="上限"):
        store.verify(runtime_root, solver)


def test_profile_store_serializes_concurrent_capacity_updates(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    solver = _solver(tmp_path / "trusted" / "TopOptSolver.exe")
    store = RuntimeProfileStore(
        max_profiles=32,
        environ={"TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST": str(solver)},
    )
    with ThreadPoolExecutor(max_workers=8) as pool:
        profiles = list(pool.map(lambda _: store.verify(runtime_root, solver), range(24)))
    assert len({item.profile_id for item in profiles}) == 24
    assert store.profile_count == 24


def test_profile_detects_runtime_dll_replacement(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    dll = _runtime_layout(runtime_root)
    solver = _solver(tmp_path / "trusted" / "TopOptSolver.exe")
    store = RuntimeProfileStore(
        environ={"TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST": str(solver)}
    )
    profile = store.verify(runtime_root, solver)
    dll.write_bytes(b"replacement")
    with pytest.raises(RuntimeProfileError, match="DLL.*变化"):
        store.resolve(profile.profile_id)


def test_runtime_child_environment_drops_parent_secrets(tmp_path: Path) -> None:
    parent = {
        "PATH": r"C:\unsafe",
        "SystemRoot": r"C:\Windows",
        "WINDIR": r"C:\Windows",
        "COMSPEC": r"C:\Windows\System32\cmd.exe",
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
        "PATHEXT": ".EXE;.BAT",
        "PROCESSOR_ARCHITECTURE": "AMD64",
        "TOPPILOT_DESKTOP_TOKEN": "desktop-secret",
        "DASHSCOPE_API_KEY": "cloud-secret",
        "UNRELATED_SECRET": "nope",
    }
    child = build_runtime_environment(tmp_path / "runtime", parent)
    assert child["SystemRoot"] == parent["SystemRoot"]
    assert child["COMSPEC"] == parent["COMSPEC"]
    assert "TOPPILOT_DESKTOP_TOKEN" not in child
    assert "DASHSCOPE_API_KEY" not in child
    assert "UNRELATED_SECRET" not in child


def test_silent_runtime_process_observes_timeout_without_blocking_on_stdout(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    started = time.monotonic()
    with pytest.raises(MatlabInfrastructureError, match="超时"):
        run_runtime_solver(
            [sys.executable, "-c", "import time; time.sleep(1.5)"],
            {},
            tmp_path / "run",
            runtime_root=runtime_root,
            timeout_seconds=0.1,
            parent_env=os.environ,
        )
    assert time.monotonic() - started < 0.8


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object protection is Windows-specific")
def test_runtime_timeout_terminates_descendant_process_tree(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    child_pid_file = tmp_path / "child-pid.txt"
    parent_code = (
        "import pathlib, subprocess, sys, time; "
        "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); "
        "time.sleep(10)"
    )
    child_pid: int | None = None
    try:
        with pytest.raises(MatlabInfrastructureError, match="超时"):
            run_runtime_solver(
                [sys.executable, "-c", parent_code, str(child_pid_file)],
                {},
                tmp_path / "run-with-child",
                runtime_root=runtime_root,
                timeout_seconds=0.5,
                parent_env=os.environ,
            )
        assert child_pid_file.is_file()
        child_pid = int(child_pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            output = subprocess.run(
                ["tasklist", "/FI", f"PID eq {child_pid}", "/NH"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
            ).stdout
            if str(child_pid) not in output:
                break
            time.sleep(0.02)
        assert str(child_pid) not in output
    finally:
        if child_pid is not None:
            subprocess.run(
                ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def test_solver_is_staged_and_verified_before_execution(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    source = _solver(tmp_path / "trusted" / "TopOptSolver.exe")
    store = RuntimeProfileStore(
        environ={"TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST": str(source)}
    )
    profile = store.resolve(store.verify(runtime_root, source).profile_id)

    staged = stage_runtime_solver(profile, tmp_path / "run")
    source.write_bytes(b"replaced-after-staging")

    assert staged.parent == tmp_path / "run" / "runtime-staging"
    assert staged.read_bytes() == b"solver-v1"
    assert staged != source
