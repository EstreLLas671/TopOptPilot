from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from idesktop_v2.api.app import app
from idesktop_v2.engineering.runtime_discovery import RuntimeInstallation
from idesktop_v2.engineering.runtime_profiles import RuntimeProfileError, RuntimeProfileStore

def _runtime_layout(root: Path) -> None:
    dll = root / "runtime" / "win64" / "mclmcrrt24_2.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"runtime-r2024b")
    uninstaller = root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe"
    uninstaller.parent.mkdir(parents=True)
    uninstaller.write_bytes(b"uninstaller")

def _solver_layout(project_root: Path, release: str = "R2024b") -> Path:
    solver_dir = project_root / "matlab" / "dist" / "solver"
    solver_dir.mkdir(parents=True)
    solver = solver_dir / "TopOptSolver.exe"
    solver.write_bytes(b"compiled-solver")
    (solver_dir / "compiler-info.json").write_text(
        json.dumps({"matlabRelease": release.removeprefix("R")}),
        encoding="utf-8",
    )
    return solver

def test_auto_profile_pairs_only_a_trusted_version_matched_solver(tmp_path: Path) -> None:
    runtime_root = tmp_path / "MATLAB Runtime" / "R2024b"
    _runtime_layout(runtime_root)
    solver = _solver_layout(tmp_path)
    store = RuntimeProfileStore(environ={}, project_root=tmp_path)

    first = store.verify_compatible_installation(runtime_root, "R2024b")
    second = store.verify_compatible_installation(runtime_root, "R2024b")

    assert first.solver_executable == solver.resolve()
    assert second.profile_id == first.profile_id

def test_auto_profile_refuses_a_runtime_whose_release_does_not_match_solver(tmp_path: Path) -> None:
    runtime_root = tmp_path / "MATLAB Runtime" / "R2025b"
    _runtime_layout(runtime_root)
    _solver_layout(tmp_path, release="R2024b")
    store = RuntimeProfileStore(environ={}, project_root=tmp_path)

    with pytest.raises(RuntimeProfileError) as error:
        store.verify_compatible_installation(runtime_root, "R2025b")

    assert error.value.code == "RUNTIME_SOLVER_MISMATCH"

def test_runtime_installations_separates_installation_health_from_run_readiness(
    monkeypatch, tmp_path: Path
) -> None:
    from idesktop_v2.engineering import router as engineering_router

    root = tmp_path / "MATLAB Runtime" / "R2025b"
    installation = RuntimeInstallation(
        release="R2025b",
        version="25.2.0",
        path=root,
        source="registry",
        usable=True,
        reason="MATLAB Runtime 安装完整",
        dll_path=root / "runtime" / "win64" / "mclmcrrt25_2.dll",
        uninstaller_path=root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe",
    )
    monkeypatch.setattr(engineering_router.runtime_inventory, "refresh", lambda: [installation])

    def incompatible(*_args):
        raise RuntimeProfileError(
            "已安装 Runtime 与受信任求解器版本不匹配",
            code="RUNTIME_SOLVER_MISMATCH",
        )

    monkeypatch.setattr(
        engineering_router.runtime_profiles,
        "verify_compatible_installation",
        incompatible,
        raising=False,
    )

    payload = TestClient(app).get("/api/engineering/runtime/installations").json()

    assert payload["usable"] is True
    assert payload["runReady"] is False
    assert payload["installations"][0]["usable"] is True
    assert payload["installations"][0]["runReady"] is False
    assert payload["installations"][0]["profileId"] is None
    assert payload["installations"][0]["runReason"] == "已安装 Runtime 与受信任求解器版本不匹配"
