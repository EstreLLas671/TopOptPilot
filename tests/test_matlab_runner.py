from __future__ import annotations

import json
from pathlib import Path

import pytest

from idesktop_v2.engineering.matlab_runner import (
    MatlabInfrastructureError,
    build_engineering_matlab_config,
    build_matlab_batch_expression,
    build_runtime_command,
    build_runtime_environment,
    read_matlab_status,
)


def test_build_matlab_config_maps_engineering_task_without_demo_flags() -> None:
    config = build_engineering_matlab_config({
        "load_case": "cantilever",
        "geometry": {"nelx": 12, "nely": 8, "nelz": 3},
        "params": {"volfrac": 0.35, "max_iter": 7, "rmin": 2.0},
    })
    assert config["bc_type"] == "cantilever"
    assert config["nelx"] == 12 and config["nely"] == 8 and config["nelz"] == 3
    assert config["max_iterations"] == 7
    assert config["display"] is False
    assert config["live_stress_snapshots"] is True
    assert config["provenance_mode"] == "engineering-local-matlab"


def test_matlab_batch_expression_escapes_windows_paths() -> None:
    expression = build_matlab_batch_expression(Path(r"C:\work\O'Brien\config.json"), Path(r"C:\work\output"))
    assert "run_topopt_job" in expression
    assert "O''Brien" in expression
    assert "C:/work/output" in expression


def test_runtime_command_requires_a_verified_executable(tmp_path: Path) -> None:
    with pytest.raises(MatlabInfrastructureError, match="编译 Runtime 求解器"):
        build_runtime_command(tmp_path / "missing.exe", tmp_path / "config.json", tmp_path)

    solver = tmp_path / "TopOptSolver.exe"
    solver.write_bytes(b"placeholder")
    command = build_runtime_command(solver, tmp_path / "config.json", tmp_path)
    assert command == [str(solver), str(tmp_path / "config.json"), str(tmp_path)]


def test_read_matlab_status_rejects_malformed_or_nonterminal_payload(tmp_path: Path) -> None:
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"state": "running", "progress": 0.4}), encoding="utf-8")
    assert read_matlab_status(status)["state"] == "running"
    status.write_text("not-json", encoding="utf-8")
    with pytest.raises(MatlabInfrastructureError, match="status.json"):
        read_matlab_status(status)


def test_runtime_environment_prepends_required_directories_without_mutating_parent(tmp_path: Path) -> None:
    runtime_root = tmp_path / "R2025b"
    parent = {"PATH": r"C:\\Windows\\System32", "UNCHANGED": "yes"}

    child = build_runtime_environment(runtime_root, parent)

    expected = [
        runtime_root / "runtime" / "win64",
        runtime_root / "bin" / "win64",
        runtime_root / "sys" / "os" / "win64",
        runtime_root / "extern" / "bin" / "win64",
    ]
    assert child["PATH"].split(";")[:4] == [str(path.resolve()) for path in expected]
    assert child["PATH"] == ";".join(str(path.resolve()) for path in expected)
    assert parent["PATH"] not in child["PATH"]
    assert "UNCHANGED" not in child
    assert parent == {"PATH": r"C:\\Windows\\System32", "UNCHANGED": "yes"}
