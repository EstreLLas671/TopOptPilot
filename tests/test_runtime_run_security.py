from __future__ import annotations

import builtins
import hashlib
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from idesktop_v2.api.app import app
from idesktop_v2.artifacts.models import SolverLane
from idesktop_v2.engineering import router as engineering_router
from idesktop_v2.engineering import runs as engineering_runs
from idesktop_v2.engineering.runs import RunCreateRequest, RunManager, _Run
from idesktop_v2.engineering.runtime_profiles import RuntimeProfileStore


def _runtime_layout(root: Path) -> None:
    dll = root / "runtime" / "win64" / "mclmcrrt25_2.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"runtime-dll")
    uninstaller = root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe"
    uninstaller.parent.mkdir(parents=True)
    uninstaller.write_bytes(b"uninstaller")


def _profile(tmp_path: Path):
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    solver = tmp_path / "trusted" / "TopOptSolver.exe"
    solver.parent.mkdir(parents=True)
    solver.write_bytes(b"compiled-solver")
    store = RuntimeProfileStore(
        environ={"IDESKTOP_RUNTIME_SOLVER_ALLOWLIST": str(solver)}
    )
    return store, store.verify(runtime_root, solver)


def _wait(record: _Run, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = record.public()
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_compiled_api_requires_profile_and_other_lanes_forbid_it(monkeypatch) -> None:
    monkeypatch.delenv("IDESKTOP_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("IDESKTOP_RUNTIME_SOLVER", raising=False)
    client = TestClient(app)

    missing = client.post(
        "/api/engineering/runs",
        json={"lane": "compiled-runtime", "ownerId": "runtime", "task": {}},
    )
    unrelated = client.post(
        "/api/engineering/runs",
        json={
            "lane": "python-fem",
            "ownerId": "python",
            "runtimeProfileId": "runtime-stale",
            "task": {},
        },
    )

    assert missing.status_code == 422
    assert unrelated.status_code == 422


def test_internal_headless_entry_injects_only_a_trusted_environment_profile(monkeypatch) -> None:
    captured: list[RunCreateRequest] = []
    profile = SimpleNamespace(profile_id="runtime-headless")
    manager = RunManager()
    monkeypatch.setattr(engineering_runs.runtime_profiles, "verify_environment", lambda: profile)
    monkeypatch.setattr(manager, "submit", lambda request: captured.append(request) or SimpleNamespace())
    manager.submit_headless_runtime(
        RunCreateRequest(lane=SolverLane.COMPILED_RUNTIME, task={})
    )
    assert captured[0].runtime_profile_id == "runtime-headless"


def test_local_matlab_run_uses_full_probe_timeout(monkeypatch, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    installation = SimpleNamespace(executable=r"C:\MATLAB\R2024b\bin\matlab.exe")
    record = _Run(
        "run-local-matlab",
        "engineering",
        SolverLane.LOCAL_MATLAB,
        {},
        "a" * 64,
        run_dir,
    )
    captured: dict[str, float] = {}

    async def fake_probe(_installation, *, timeout_seconds: float = 45.0):
        captured["timeout_seconds"] = timeout_seconds
        return SimpleNamespace(usable=True)

    monkeypatch.setenv("IDESKTOP_MATLAB_PATH", installation.executable)
    monkeypatch.setattr(engineering_runs, "engineering_matlab_source_root", lambda: tmp_path)
    monkeypatch.setattr(
        engineering_runs,
        "discover_matlab_installations",
        lambda **_kwargs: [installation],
    )
    monkeypatch.setattr(engineering_runs, "probe_matlab_installation", fake_probe)
    monkeypatch.setattr(
        engineering_runs,
        "run_matlab_batch",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "objective": 1.0,
            "volume_fraction": 0.4,
            "iterations": 1,
            "provenance": {"resultKind": "solver", "backend": "local-matlab"},
        },
    )

    RunManager()._run_external(record, None)

    assert captured["timeout_seconds"] == 45.0


def test_external_matlab_progress_callback_updates_events_without_rewriting_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    installation = SimpleNamespace(executable=r"C:\MATLAB\R2024b\bin\matlab.exe")
    record = _Run("run-local-progress", "engineering", SolverLane.LOCAL_MATLAB, {}, "a" * 64, run_dir)

    async def fake_probe(_installation, **_kwargs):
        return SimpleNamespace(usable=True)

    def fake_runner(*_args, **kwargs):
        snapshots = run_dir / "snapshots"
        snapshots.mkdir()
        density = snapshots / "iter_0003_density.bin"
        density.write_bytes(b"\x00\x00\x80?")
        kwargs["progress"](
            3,
            {
                "compliance": 12.5,
                "volume_fraction": 0.4,
                "gray_ratio": 0.2,
                "snapshot": {
                    "densityPath": "snapshots/iter_0003_density.bin",
                    "stressPath": None,
                    "shape": [1, 1],
                    "dtype": "float32",
                    "order": "F",
                    "dimension": "2d",
                },
            },
        )
        return {
            "status": "completed",
            "objective": 12.5,
            "volume_fraction": 0.4,
            "gray_ratio": 0.2,
            "iterations": 3,
            "provenance": {"resultKind": "solver", "backend": "local-matlab"},
        }

    monkeypatch.setenv("IDESKTOP_MATLAB_PATH", installation.executable)
    monkeypatch.setattr(engineering_runs, "engineering_matlab_source_root", lambda: tmp_path)
    monkeypatch.setattr(engineering_runs, "discover_matlab_installations", lambda **_kwargs: [installation])
    monkeypatch.setattr(engineering_runs, "probe_matlab_installation", fake_probe)
    monkeypatch.setattr(engineering_runs, "run_matlab_batch", fake_runner)

    RunManager()._worker(record, None)

    progress_events = [event for event in record.events if event["type"] == "progress"]
    assert len(progress_events) == 1
    assert progress_events[0]["iteration"] == 3
    assert progress_events[0]["metrics"] == {
        "iteration": 3.0,
        "iterations": 3.0,
        "compliance": 12.5,
        "volumeFraction": 0.4,
        "grayRatio": 0.2,
    }
    assert not (run_dir / "snapshots" / "iteration-0003.json").exists()
    assert progress_events[0]["snapshot"]["densityPath"] == "snapshots/iter_0003_density.bin"
    assert len(progress_events[0]["snapshot"]["densitySha256"]) == 64
    assert [item.relative_path for item in record.snapshots] == [
        "snapshots/iter_0003_density.bin"
    ]


def test_invalid_profile_never_falls_back_and_has_unverified_provenance(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IDESKTOP_V2_DATA_DIR", str(tmp_path / "data"))
    runtime_root = tmp_path / "runtime"
    _runtime_layout(runtime_root)
    solver = tmp_path / "trusted" / "TopOptSolver.exe"
    solver.parent.mkdir(parents=True)
    solver.write_bytes(b"solver")
    monkeypatch.setenv("IDESKTOP_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("IDESKTOP_RUNTIME_SOLVER", str(solver))
    monkeypatch.setenv("IDESKTOP_RUNTIME_SOLVER_ALLOWLIST", str(solver))

    manager = RunManager()
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "solver.topopt_engine":
            raise AssertionError("compiled Runtime must not import the Python solver")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    record = manager.submit(
        RunCreateRequest(
            lane=SolverLane.COMPILED_RUNTIME,
            runtime_profile_id="runtime-does-not-exist",
            task={},
        )
    )
    payload = _wait(record)

    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "RUNTIME_PROFILE_STALE"
    assert payload["error"]["source"] == "runtime"
    assert payload["provenance"]["resultKind"] != "solver"
    assert str(runtime_root) not in str(payload["provenance"])
    assert str(solver) not in str(payload["provenance"])


def test_external_runtime_executes_private_staged_solver(monkeypatch, tmp_path: Path) -> None:
    store, profile = _profile(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record = _Run(
        "run-staged",
        "engineering",
        SolverLane.COMPILED_RUNTIME,
        {},
        "a" * 64,
        run_dir,
        runtime_profile_id=profile.profile_id,
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(engineering_runs.runtime_profiles, "resolve", store.resolve)

    def fake_runner(command, task, output_dir, **kwargs):
        captured["command"] = command
        return {
            "status": "completed",
            "objective": 1.0,
            "volume_fraction": 0.4,
            "iterations": 1,
            "provenance": {
                "resultKind": "solver",
                "backend": "compiled-runtime",
                "lane": "compiled-runtime",
            },
        }

    monkeypatch.setattr(engineering_runs, "run_runtime_solver", fake_runner)
    result = RunManager()._run_external(record, None)
    staged = Path(captured["command"][0])

    assert staged.parent == run_dir / "runtime-staging"
    assert staged != profile.solver_executable
    assert hashlib.sha256(staged.read_bytes()).hexdigest() == profile.solver_identity.sha256
    assert result["provenance"]["solverSha256"] == profile.solver_identity.sha256
    assert str(profile.solver_executable) not in str(result["provenance"])
