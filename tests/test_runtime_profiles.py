from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from topoptpilot_desktop.engineering.runtime_profiles import RuntimeProfileError, RuntimeProfileStore


def _runtime_layout(root: Path) -> Path:
    dll = root / "runtime" / "win64" / "mclmcrrt25_2.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"runtime-dll")
    uninstaller = root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe"
    uninstaller.parent.mkdir(parents=True)
    uninstaller.write_bytes(b"uninstaller")
    return dll


def test_runtime_profile_binds_independent_solver_and_revalidates_identity(tmp_path: Path) -> None:
    runtime_root = tmp_path / "MATLAB Runtime" / "R2025b"
    _runtime_layout(runtime_root)
    solver = tmp_path / "application-resources" / "solver" / "TopOptSolver.exe"
    solver.parent.mkdir(parents=True)
    solver.write_bytes(b"compiled-solver-v1")
    store = RuntimeProfileStore(environ={"TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST": str(solver)})

    profile = store.verify(runtime_root, solver)

    assert profile.usable is True
    assert profile.runtime_root == runtime_root.resolve()
    assert profile.solver_executable == solver.resolve()
    assert store.resolve(profile.profile_id).solver_executable == solver.resolve()

    solver.write_bytes(b"compiled-solver-v2")
    with pytest.raises(RuntimeProfileError, match="已变化"):
        store.resolve(profile.profile_id)


def test_runtime_profile_requires_ready_root_and_regular_exe(tmp_path: Path) -> None:
    store = RuntimeProfileStore()
    solver = tmp_path / "solver.bin"
    solver.write_bytes(b"not-an-exe")

    with pytest.raises(RuntimeProfileError, match="Runtime"):
        store.verify(tmp_path / "missing-runtime", solver)

    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    with pytest.raises(RuntimeProfileError, match="\\.exe"):

        store.verify(runtime_root, solver)

def test_runtime_profile_trusts_solver_staged_in_bundled_runtime_resources(tmp_path: Path) -> None:
    runtime_root = tmp_path / "resources" / "runtime" / "MATLAB Runtime" / "R2024b"
    _runtime_layout(runtime_root)
    solver = tmp_path / "resources" / "runtime" / "solver" / "TopOptSolver.exe"
    solver.parent.mkdir(parents=True)
    solver.write_bytes(b"bundled-compiled-solver")
    store = RuntimeProfileStore(
        environ={"TOPPILOT_RESOURCE_ROOT": str(tmp_path / "resources")},
        project_root=tmp_path / "source",
    )

    profile = store.verify(runtime_root, solver)

    assert profile.solver_executable == solver.resolve()


def _bundled_runtime_layout(resource_root: Path) -> tuple[Path, Path, Path]:
    runtime_root = resource_root / "runtime" / "MATLAB Runtime" / "R2024b"
    dll = _runtime_layout(runtime_root)
    solver = resource_root / "runtime" / "solver" / "TopOptSolver.exe"
    solver.parent.mkdir(parents=True)
    solver.write_bytes(b"bundled-solver-v1")
    manifest = {
        "schemaVersion": 1,
        "packageKind": "topoptpilot-runtime",
        "runtimeRoot": "runtime/MATLAB Runtime/R2024b",
        "runtimeDll": "runtime/MATLAB Runtime/R2024b/runtime/win64/mclmcrrt25_2.dll",
        "solver": "runtime/solver/TopOptSolver.exe",
        "runtimeDllSha256": hashlib.sha256(dll.read_bytes()).hexdigest(),
        "solverSha256": hashlib.sha256(solver.read_bytes()).hexdigest(),
    }
    manifest_path = resource_root / "runtime" / "runtime-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return runtime_root, dll, solver


def test_runtime_profile_registers_hash_verified_bundled_manifest(tmp_path: Path) -> None:
    resource_root = tmp_path / "resources"
    runtime_root, dll, solver = _bundled_runtime_layout(resource_root)
    store = RuntimeProfileStore(
        environ={"TOPPILOT_RESOURCE_ROOT": str(resource_root)},
        project_root=tmp_path / "source",
    )

    profile = store.verify_bundled_resource()

    assert profile is not None
    assert profile.runtime_root == runtime_root.resolve()
    assert profile.dll_path == dll.resolve()
    assert profile.solver_executable == solver.resolve()


def test_runtime_profile_rejects_tampered_bundled_solver(tmp_path: Path) -> None:
    resource_root = tmp_path / "resources"
    _, _, solver = _bundled_runtime_layout(resource_root)
    solver.write_bytes(b"tampered-solver")
    store = RuntimeProfileStore(
        environ={"TOPPILOT_RESOURCE_ROOT": str(resource_root)},
        project_root=tmp_path / "source",
    )

    with pytest.raises(RuntimeProfileError, match="摘要"):
        store.verify_bundled_resource()


def test_runtime_profile_reports_no_bundle_for_standard_package(tmp_path: Path) -> None:
    store = RuntimeProfileStore(environ={"TOPPILOT_RESOURCE_ROOT": str(tmp_path)})

    assert store.verify_bundled_resource() is None
