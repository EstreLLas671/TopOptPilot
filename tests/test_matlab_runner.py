from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from idesktop_v2.engineering import matlab_runner
from idesktop_v2.engineering.matlab_runner import (
    MatlabInfrastructureError,
    build_engineering_matlab_config,
    build_matlab_batch_expression,
    build_runtime_command,
    build_runtime_environment,
    read_matlab_status,
    run_matlab_batch,
    run_runtime_solver,
)


def test_build_matlab_config_maps_engineering_task_without_demo_flags() -> None:
    config = build_engineering_matlab_config({
        "load_case": "cantilever",
        "geometry": {"nelx": 12, "nely": 8, "nelz": 3},
        "params": {"volfrac": 0.35, "penal": 3.2, "max_iter": 7, "min_iter": 4, "rmin": 2.0, "filter_strategy": "adaptive", "accuracy": "high"},
    })
    assert config["bc_type"] == "cantilever"
    assert config["nelx"] == 12 and config["nely"] == 8 and config["nelz"] == 3
    assert config["max_iterations"] == 7
    assert config["min_iterations"] == 4
    assert config["penal"] == 3.2
    assert config["filter_strategy"] == "adaptive"
    assert config["accuracy"] == "high"
    assert config["display"] is False
    assert config["live_stress_snapshots"] is True
    assert config["provenance_mode"] == "engineering-local-matlab"


def test_build_matlab_config_routes_explicit_2d_and_3d_sources() -> None:
    two_d = build_engineering_matlab_config({
        "dimension": "2d",
        "geometry": {"nelx": 16, "nely": 8, "nelz": 9},
    })
    three_d = build_engineering_matlab_config({
        "dimension": "3d",
        "geometry": {"nelx": 16, "nely": 8, "nelz": 5},
    })

    assert two_d["solver_dimension"] == "2d"
    assert two_d["nelz"] == 1
    assert three_d["solver_dimension"] == "3d"
    assert three_d["nelz"] == 5


def test_manifest_progress_includes_only_committed_real_snapshot_files(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    density = snapshots / "iter_0001_density.bin"
    density.write_bytes(b"\x00\x00\x80?")
    (snapshots / "manifest.json").write_text(
        json.dumps({
            "dtype": "float32",
            "order": "F",
            "dimension": "2d",
            "shape": [1, 1],
            "frames": [{
                "iteration": 1,
                "objective": 8.5,
                "volume_fraction": 0.4,
                "density_file": density.name,
                "stress_file": "",
            }],
        }),
        encoding="utf-8",
    )
    published: list[tuple[int, dict]] = []

    matlab_runner.publish_manifest_progress(
        tmp_path,
        set(),
        lambda iteration, state: published.append((iteration, state)),
    )

    assert published[0][1]["snapshot"] == {
        "densityPath": "snapshots/iter_0001_density.bin",
        "stressPath": None,
        "shape": [1, 1],
        "dtype": "float32",
        "order": "F",
        "dimension": "2d",
    }

def test_matlab_batch_expression_escapes_windows_paths() -> None:
    expression = build_matlab_batch_expression(Path(r"C:\work\O'Brien\config.json"), Path(r"C:\work\output"))
    assert "run_topopt_job" in expression
    assert "O''Brien" in expression
    assert "C:/work/output" in expression


def test_matlab_batch_accepts_discovered_string_executable_path(tmp_path: Path) -> None:
    with pytest.raises(MatlabInfrastructureError, match="MATLAB 可执行文件不存在"):
        run_matlab_batch(
            str(tmp_path / "missing-matlab.exe"),
            {},
            tmp_path / "run",
            source_root=tmp_path,
        )


def test_manifest_progress_publishes_new_frames_in_order_and_recovers_after_partial_write(
    tmp_path: Path,
) -> None:
    publish = getattr(matlab_runner, "publish_manifest_progress", None)
    assert callable(publish), "manifest progress publisher is missing"

    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    manifest = snapshots / "manifest.json"
    manifest.write_text('{"frames":', encoding="utf-8")
    seen: set[int] = set()
    published: list[tuple[int, dict]] = []

    publish(tmp_path, seen, lambda iteration, state: published.append((iteration, state)))
    assert published == []
    assert seen == set()

    manifest.write_text(
        json.dumps(
            {
                "frames": [
                    {"iteration": 2, "objective": 18.0, "volume_fraction": 0.39},
                    {"iteration": 1, "objective": 20.0, "volume_fraction": 0.4, "gray_ratio": 0.25},
                ]
            }
        ),
        encoding="utf-8",
    )
    publish(tmp_path, seen, lambda iteration, state: published.append((iteration, state)))
    assert published == [
        (1, {"compliance": 20.0, "volume_fraction": 0.4, "gray_ratio": 0.25}),
        (2, {"compliance": 18.0, "volume_fraction": 0.39}),
    ]

    manifest.write_text(
        json.dumps(
            {
                "frames": [
                    {"iteration": 1, "objective": 20.0, "volume_fraction": 0.4},
                    {"iteration": 2, "objective": 18.0, "volume_fraction": 0.39},
                    {"iteration": 3, "objective": 17.0, "volume_fraction": 0.4},
                ]
            }
        ),
        encoding="utf-8",
    )
    publish(tmp_path, seen, lambda iteration, state: published.append((iteration, state)))
    publish(tmp_path, seen, lambda iteration, state: published.append((iteration, state)))
    assert [iteration for iteration, _state in published] == [1, 2, 3]
    assert seen == {1, 2, 3}


def test_manifest_progress_ignores_invalid_and_late_required_metrics(
    tmp_path: Path,
) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    manifest = snapshots / "manifest.json"
    manifest.write_text(
        """{"frames":[
        {"iteration":1,"objective":"invalid","volume_fraction":0.4},
        {"iteration":2,"objective":1e309,"volume_fraction":0.4},
        {"iteration":3,"objective":3.0,"volume_fraction":{"bad":true}},
        {"iteration":4,"objective":4.0,"volume_fraction":0.4,"gray_ratio":"invalid"},
        {"iteration":5,"objective":NaN,"volume_fraction":0.4}
        ]}""",
        encoding="utf-8",
    )
    seen: set[int] = set()
    published: list[tuple[int, dict]] = []

    matlab_runner.publish_manifest_progress(
        tmp_path,
        seen,
        lambda iteration, state: published.append((iteration, state)),
    )

    assert published == [
        (
            4,
            {
                "compliance": 4.0,
                "volume_fraction": 0.4,
                "gray_ratio": None,
            },
        )
    ]
    assert seen == {4}

    manifest.write_text(
        json.dumps(
            {
                "frames": [
                    {
                        "iteration": 1,
                        "objective": 5.0,
                        "volume_fraction": 0.35,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    matlab_runner.publish_manifest_progress(
        tmp_path,
        seen,
        lambda iteration, state: published.append((iteration, state)),
    )

    assert [iteration for iteration, _state in published] == [4]
    assert seen == {4}

    manifest.write_text(
        json.dumps(
            {
                "frames": [
                    {
                        "iteration": 5,
                        "objective": 3.5,
                        "volume_fraction": 0.38,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    matlab_runner.publish_manifest_progress(
        tmp_path,
        seen,
        lambda iteration, state: published.append((iteration, state)),
    )

    iterations = [iteration for iteration, _state in published]
    assert iterations == [4, 5]
    assert iterations == sorted(iterations)
    assert seen == {4, 5}


def test_manifest_progress_retries_frame_after_callback_exception(tmp_path: Path) -> None:
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "manifest.json").write_text(
        json.dumps(
            {
                "frames": [
                    {
                        "iteration": 5,
                        "objective": 7.0,
                        "volume_fraction": 0.4,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    seen: set[int] = {4}
    attempts = 0

    def failing_callback(_iteration, _state):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("consumer temporarily unavailable")

    matlab_runner.publish_manifest_progress(tmp_path, seen, failing_callback)

    assert attempts == 1
    assert seen == {4}

    published: list[tuple[int, dict]] = []
    matlab_runner.publish_manifest_progress(
        tmp_path,
        seen,
        lambda iteration, state: published.append((iteration, state)),
    )
    assert published == [
        (5, {"compliance": 7.0, "volume_fraction": 0.4})
    ]
    assert seen == {4, 5}


def test_runtime_runner_polls_manifest_and_performs_final_scan(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "status.json").write_text(
        json.dumps({"state": "completed"}),
        encoding="utf-8",
    )
    (tmp_path / "result_summary.json").write_text("{}", encoding="utf-8")

    class FakeProcess:
        returncode = 0

        def __init__(self) -> None:
            self.stdout = io.StringIO("")
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

    scans: list[int] = []
    published: list[tuple[int, dict]] = []

    def fake_publish(_output_dir, _seen, progress):
        scans.append(len(scans) + 1)
        if len(scans) == 2:
            progress(1, {"compliance": 9.0, "volume_fraction": 0.4})

    monkeypatch.setattr(matlab_runner.subprocess, "Popen", lambda *_args, **_kwargs: FakeProcess())
    monkeypatch.setattr(
        matlab_runner,
        "publish_manifest_progress",
        fake_publish,
        raising=False,
    )

    run_runtime_solver(
        ["TopOptSolver.exe"],
        {},
        tmp_path,
        runtime_root=tmp_path / "runtime",
        parent_env={},
        progress=lambda iteration, state: published.append((iteration, state)),
    )

    assert len(scans) >= 2
    assert published == [(1, {"compliance": 9.0, "volume_fraction": 0.4})]


def test_runtime_runner_terminates_process_tree_when_polling_raises(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class AliveProcess:
        returncode = None

        def __init__(self) -> None:
            self.stdout = io.StringIO("")
            self.terminate_called = False

        def poll(self):
            return None

        def terminate(self):
            self.terminate_called = True

    process = AliveProcess()
    tree_terminations = []
    monkeypatch.setattr(
        matlab_runner.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        matlab_runner,
        "publish_manifest_progress",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("poll failed")
        ),
    )
    monkeypatch.setattr(
        matlab_runner,
        "_terminate_process_tree",
        lambda running: tree_terminations.append(running),
    )

    with pytest.raises(RuntimeError, match="poll failed"):
        run_runtime_solver(
            ["TopOptSolver.exe"],
            {},
            tmp_path,
            runtime_root=tmp_path / "runtime",
            parent_env={},
            progress=lambda *_args: None,
        )

    assert tree_terminations == [process]

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
