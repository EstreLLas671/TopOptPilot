"""Verified MATLAB batch and compiled Runtime runner for engineering jobs.

This module owns the engineering MATLAB lane only.  It never turns a failed
MATLAB/MCR process into a Python success; callers receive an infrastructure
error instead.
"""

from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping


_PROCESS_JOB_ATTRIBUTE = "_topoptpilot_windows_job_handle"
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000


class MatlabInfrastructureError(RuntimeError):
    """Raised when MATLAB/Runtime infrastructure cannot execute a job."""

    def __init__(self, message: str, *, code: str = "MATLAB_INFRASTRUCTURE") -> None:
        super().__init__(message)
        self.code = code


def _matlab_quote(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


_UNIT_TO_METERS = {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "um": 1e-6}
_DEFAULT_CELL_SIZE_M = 0.25


def _resolve_physical_grid(geometry: dict[str, Any], dimension: str, params: dict[str, Any]) -> tuple[int, int, int]:
    existing = (geometry.get("nelx"), geometry.get("nely"), geometry.get("nelz"))
    if all(isinstance(value, int) and value > 0 for value in existing[:2]) and (dimension == "2d" or (isinstance(existing[2], int) and existing[2] > 0)):
        return int(existing[0]), int(existing[1]), 1 if dimension == "2d" else int(existing[2])
    dimensions = geometry.get("dimensions")
    if not isinstance(dimensions, (list, tuple)) or len(dimensions) < 2:
        return int(params.get("nelx", 24)), int(params.get("nely", 12)), 1 if dimension == "2d" else int(params.get("nelz", 4))
    unit = str(geometry.get("unit") or "m").strip().lower()
    scale = _UNIT_TO_METERS.get(unit)
    if scale is None:
        raise ValueError("geometry.unit 仅支持 m、mm、cm 或 um")
    count = 2 if dimension == "2d" else 3
    values = [float(dimensions[index]) for index in range(count)]
    if any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("geometry.dimensions 必须为有限正数")
    cell = geometry.get("cell_size_m", _DEFAULT_CELL_SIZE_M)
    if not isinstance(cell, (int, float)) or not math.isfinite(float(cell)) or float(cell) <= 0:
        raise ValueError("geometry.cell_size_m 必须为正数")
    grid = [max(1, int(math.ceil(value * scale / float(cell)))) for value in values]
    return grid[0], grid[1], 1 if dimension == "2d" else grid[2]

def build_engineering_matlab_config(task: dict[str, Any]) -> dict[str, Any]:
    geometry = task.get("geometry") or {}
    params = task.get("params") or {}
    material = task.get("material") or {}
    if not isinstance(geometry, dict):
        geometry = {}
    if not isinstance(params, dict):
        params = {}
    if not isinstance(material, dict):
        material = {}
    load_case = str(task.get("load_case") or task.get("bc_type") or "cantilever")
    if load_case.lower() == "vertical":
        load_case = "MBB"
    elif load_case.lower() == "lateral":
        load_case = "cantilever"
    dimension = str(task.get("dimension") or task.get("solver_dimension") or "3d").lower()
    if dimension not in {"2d", "3d"}:
        raise ValueError("task.dimension 仅支持 2d 或 3d")
    nelx, nely, nelz = _resolve_physical_grid(geometry, dimension, params)
    return {
        "solver_dimension": dimension,
        "bc_type": load_case,
        "nelx": nelx,
        "nely": nely,
        "nelz": nelz,
        "volfrac": float(params.get("volfrac", task.get("volfrac", 0.4))),
        "penal": float(params.get("penal", 3.0)),
        "rmin": float(params.get("rmin", 1.5)),
        "max_iterations": int(params.get("max_iter", params.get("max_iterations", 80))),
        "min_iterations": int(params.get("min_iter", params.get("min_iterations", 1))),
        "filter_strategy": str(params.get("filter_strategy", "fixed")),
        "accuracy": str(params.get("accuracy", "standard")),
        # 科研 Step4 复用本链路时经 params 透传投影/控制器参数；
        # 工程模式自身的 task 不含这些键，默认值保持原有行为。
        "beta": float(params.get("beta", 1.0)),
        "beta_max": float(params.get("beta_max", params.get("beta", 1.0))),
        "projection": str(params.get("projection", "none")),
        "controller": str(params.get("controller", "fixed_controller")),
        "move_start": float(params.get("move_start", params.get("move", 0.2))),
        "move_end": float(params.get("move_end", params.get("move", 0.2))),
        "display": False,
        "material_preset": str(material.get("preset", "normalized")),
        "material_name": str(material.get("name", "归一化参考材料")),
        "E": float(params.get("E", material.get("E", material.get("E_GPa", 1.0)))),
        "nu": float(params.get("nu", material.get("nu", 0.3))),
        "density_kg_m3": float(material.get("density_kg_m3", 1.0)),
        "yield_strength_MPa": float(material.get("yield_strength_MPa", 1.0)),
        "verbose": True,
        "live_stress_snapshots": True,
        "render_iteration_frames": True,
        "provenance_mode": "engineering-local-matlab",
        "dimensions": geometry.get("dimensions"),
        "unit": geometry.get("unit", "m"),
        "cell_size_m": geometry.get("cell_size_m", _DEFAULT_CELL_SIZE_M),
    }


def build_matlab_batch_expression(config_path: Path, output_dir: Path) -> str:
    config = _matlab_quote(config_path)
    output = _matlab_quote(output_dir)
    return f"run_topopt_job('{config}','{output}');"


def build_runtime_command(executable: Path, config_path: Path, output_dir: Path) -> list[str]:
    executable = executable.resolve()
    if not executable.is_file():
        raise MatlabInfrastructureError(f"编译 Runtime 求解器不存在：{executable}")
    return [str(executable), str(config_path.resolve()), str(output_dir.resolve())]


def build_runtime_environment(runtime_root: Path, parent: Mapping[str, str] = os.environ) -> dict[str, str]:
    """Build a child-only Windows Runtime search path."""
    root = runtime_root.expanduser().resolve()
    required = [
        root / "runtime" / "win64",
        root / "bin" / "win64",
        root / "sys" / "os" / "win64",
        root / "extern" / "bin" / "win64",
    ]
    allowed = {
        "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT", "OS",
        "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION", "NUMBER_OF_PROCESSORS", "PROGRAMDATA",
        "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES",
        "COMMONPROGRAMFILES(X86)",
    }
    child = {key: value for key, value in parent.items() if key.upper() in allowed}
    system_root = child.get("SystemRoot") or child.get("SYSTEMROOT") or child.get("WINDIR")
    if system_root:
        windows = Path(system_root)
        required.extend([windows / "System32", windows / "System32" / "Wbem"])
    child["PATH"] = os.pathsep.join(str(path.resolve()) for path in required)
    return child


def read_matlab_status(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MatlabInfrastructureError(f"无法读取 MATLAB status.json：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("state"), str):
        raise MatlabInfrastructureError("MATLAB status.json 缺少 state")
    return payload


def _result_files(output_dir: Path) -> list[Path]:
    candidates = [output_dir / "result_summary.json", output_dir / "result.mat", output_dir / "solver.log"]
    return [path for path in candidates if path.is_file()]


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _snapshot_relative_path(snapshot_root: Path, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    root = snapshot_root.resolve()
    candidate = (root / value).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return (Path("snapshots") / relative).as_posix()


def publish_manifest_progress(
    output_dir: Path,
    seen_iterations: set[int],
    progress: Callable[[int, dict[str, Any]], None] | None = None,
) -> None:
    """Publish strictly increasing valid frames; callback failures remain retryable."""
    if progress is None:
        return
    try:
        manifest = json.loads(
            (output_dir / "snapshots" / "manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return
    if not isinstance(manifest, dict):
        return
    frames = manifest.get("frames", [])
    if isinstance(frames, dict):
        frames = [frames]
    if not isinstance(frames, list):
        return
    raw_shape = manifest.get("shape")
    shape = raw_shape if isinstance(raw_shape, list) and len(raw_shape) in {2, 3} else None
    if shape is not None and any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in shape
    ):
        shape = None
    snapshot_root = output_dir / "snapshots"

    high_water = max(seen_iterations, default=0)
    pending: list[tuple[int, dict[str, Any]]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        raw_iteration = frame.get("iteration")
        if isinstance(raw_iteration, bool):
            continue
        try:
            iteration = int(raw_iteration)
        except (TypeError, ValueError, OverflowError):
            continue
        if iteration < 1 or iteration != raw_iteration or iteration <= high_water:
            continue
        compliance = _finite_number(frame.get("objective"))
        volume_fraction = _finite_number(frame.get("volume_fraction"))
        if compliance is None or volume_fraction is None:
            continue
        density_path = _snapshot_relative_path(snapshot_root, frame.get("density_file"))
        stress_path = _snapshot_relative_path(snapshot_root, frame.get("stress_file"))
        render_path = _snapshot_relative_path(snapshot_root, frame.get("render_file"))
        state = {
            "compliance": compliance,
            "volume_fraction": volume_fraction,
        }
        if density_path is not None and shape is not None:
            state["snapshot"] = {
                "densityPath": density_path,
                "stressPath": stress_path,
                "renderPath": render_path,
                "shape": shape,
                "dtype": manifest.get("dtype", "float32"),
                "order": manifest.get("order", "F"),
                "dimension": manifest.get("dimension", "3d" if len(shape) == 3 else "2d"),
            }
        if "gray_ratio" in frame:
            state["gray_ratio"] = _finite_number(frame.get("gray_ratio"))
        pending.append((iteration, state))

    for iteration, state in sorted(pending, key=lambda item: item[0]):
        if iteration in seen_iterations:
            continue
        try:
            progress(iteration, state)
        except Exception:
            return
        seen_iterations.add(iteration)


def run_matlab_batch(
    executable: Path | str,
    task: dict[str, Any],
    output_dir: Path,
    *,
    source_root: Path,
    cancel=None,
    timeout_seconds: float | None = None,
    progress: Callable[[int, dict[str, Any]], None] | None = None,
    console: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Run ``run_topopt_job.m`` and return its verified summary.

    The caller supplies a previously probed MATLAB executable.  The subprocess
    is terminated on cancellation/timeout and a completed result requires both
    a terminal ``status.json`` and ``result_summary.json``.
    """
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise MatlabInfrastructureError(f"MATLAB 可执行文件不存在：{executable}")
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "config.json"
    matlab_config = build_engineering_matlab_config(task)
    config_path.write_text(json.dumps(matlab_config, ensure_ascii=False, indent=2), encoding="utf-8")
    expression = build_matlab_batch_expression(config_path, output_dir)
    command = [str(executable), "-wait", "-batch", f"addpath('{_matlab_quote(source_root)}'); {expression}"]
    env = os.environ.copy()
    solver_dir = str(task.get("solver_dir") or "")
    if solver_dir and Path(solver_dir).is_dir():
        # 科研 Step4 复用工程链路时指向求解器模块副本（携带投影/β 支持）；
        # run_topopt_job.m 会将其置于 bridge 副本之前。
        env["TOPOPTPILOT_SOLVER_PATH"] = str(Path(solver_dir).resolve())
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=output_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=env)
    _attach_windows_process_job(process)
    output_queue: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_read_process_output, args=(process, output_queue), daemon=True)
    reader.start()
    seen_iterations: set[int] = set()
    log_path = output_dir / "solver.log"
    try:
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            while process.poll() is None:
                if cancel is not None and cancel():
                    process.terminate()
                    raise MatlabInfrastructureError("MATLAB 工程运行已取消")
                if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                    process.terminate()
                    raise MatlabInfrastructureError("MATLAB 工程运行超时")
                _drain_process_output(output_queue, log, console)
                publish_manifest_progress(output_dir, seen_iterations, progress)
                time.sleep(0.05)
            reader.join(timeout=1)
            _drain_process_output(output_queue, log, console)
            publish_manifest_progress(output_dir, seen_iterations, progress)
        status_path = output_dir / "status.json"
        if not status_path.is_file():
            raise MatlabInfrastructureError(f"MATLAB 未生成 status.json（退出码 {process.returncode}）")
        status = read_matlab_status(status_path)
        if process.returncode != 0 or status.get("state") != "completed":
            raise MatlabInfrastructureError(f"MATLAB 求解失败：{status.get('message', '未知错误')}")
        summary_path = output_dir / "result_summary.json"
        if not summary_path.is_file():
            raise MatlabInfrastructureError("MATLAB 未生成 result_summary.json")
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MatlabInfrastructureError(f"MATLAB result_summary.json 无效：{exc}") from exc
        if not isinstance(summary, dict):
            raise MatlabInfrastructureError("MATLAB result_summary.json 必须是对象")
        summary["status"] = "completed"
        dimension = matlab_config["solver_dimension"]
        summary["provenance"] = {
            "resultKind": "solver",
            "backend": "local-matlab",
            "lane": "local-matlab",
            "solverDimension": dimension,
            "solverEntry": "TopOpt_2D/topopt_main.m" if dimension == "2d" else "TopOpt-3D/topopt3d_main.m",
        }
        summary["files"] = [path.name for path in _result_files(output_dir)]
        return summary
    finally:
        if process.poll() is None:
            _terminate_process_tree(process)
        _close_windows_process_job(process)


def _read_process_output(process: subprocess.Popen[str], output: queue.Queue[str | None]) -> None:
    try:
        if process.stdout is not None:
            for line in process.stdout:
                output.put(line)
    finally:
        output.put(None)


def _drain_process_output(
    output: queue.Queue[str | None],
    log,
    console: Callable[[str, str], None] | None = None,
) -> None:
    wrote = False
    while True:
        try:
            line = output.get_nowait()
        except queue.Empty:
            break
        if line is not None:
            log.write(line)
            wrote = True
            if console is not None:
                console("stdout", line.rstrip("\r\n"))
    if wrote:
        log.flush()


def _attach_windows_process_job(process: subprocess.Popen[Any]) -> None:
    """Attach a controlled child to a kill-on-close Windows Job Object.

    TerminateJobObject ends the root process and every descendant much faster
    than spawning taskkill. Assignment can be refused when the host itself is
    running under a restrictive job, so this routine is best-effort and leaves
    the existing taskkill fallback available.
    """
    if os.name != "nt":
        return
    process_handle = getattr(process, "_handle", None)
    if not isinstance(process_handle, int) or process_handle <= 0:
        return
    try:
        import ctypes
        from ctypes import wintypes

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        limits = _ExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        )
        assigned = configured and kernel32.AssignProcessToJobObject(
            job,
            wintypes.HANDLE(process_handle),
        )
        if not assigned:
            kernel32.CloseHandle(job)
            return
        setattr(process, _PROCESS_JOB_ATTRIBUTE, int(job))
    except (AttributeError, OSError, TypeError, ValueError):
        return


def _close_windows_process_job(process: subprocess.Popen[Any]) -> None:
    if os.name != "nt":
        return
    handle = getattr(process, _PROCESS_JOB_ATTRIBUTE, None)
    if not isinstance(handle, int) or handle <= 0:
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(wintypes.HANDLE(handle))
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    finally:
        try:
            delattr(process, _PROCESS_JOB_ATTRIBUTE)
        except AttributeError:
            pass


def _terminate_windows_process_job(process: subprocess.Popen[Any]) -> bool:
    """Terminate and release an already assigned Job Object, if present."""
    if os.name != "nt":
        return False
    handle = getattr(process, _PROCESS_JOB_ATTRIBUTE, None)
    if not isinstance(handle, int) or handle <= 0:
        return False
    terminated = False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        terminated = bool(kernel32.TerminateJobObject(wintypes.HANDLE(handle), 1))
    except (AttributeError, OSError, TypeError, ValueError):
        terminated = False
    finally:
        _close_windows_process_job(process)
    return terminated


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    terminated_by_job = _terminate_windows_process_job(process)
    if os.name == "nt" and not terminated_by_job:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    elif os.name != "nt":
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_runtime_solver(
    command: list[str],
    task: dict[str, Any],
    output_dir: Path,
    *,
    runtime_root: Path,
    cancel=None,
    timeout_seconds: float | None = None,
    progress: Callable[[int, dict[str, Any]], None] | None = None,
    console: Callable[[str, str], None] | None = None,
    parent_env: Mapping[str, str] = os.environ,
) -> dict[str, Any]:
    """Run a verified compiled solver using the same status/result contract."""
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "config.json"
    matlab_config = build_engineering_matlab_config(task)
    config_path.write_text(json.dumps(matlab_config, ensure_ascii=False, indent=2), encoding="utf-8")
    process = subprocess.Popen([*command], cwd=output_dir, env=build_runtime_environment(runtime_root, parent_env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _attach_windows_process_job(process)
    output_queue: queue.Queue[str | None] = queue.Queue()
    reader = threading.Thread(target=_read_process_output, args=(process, output_queue), daemon=True)
    reader.start()
    seen_iterations: set[int] = set()
    started = time.monotonic()
    log_path = output_dir / "solver.log"
    try:
        with log_path.open("a", encoding="utf-8", errors="replace") as log:
            while process.poll() is None:
                _drain_process_output(output_queue, log, console)
                publish_manifest_progress(output_dir, seen_iterations, progress)
                if cancel is not None and cancel():
                    _terminate_process_tree(process)
                    raise MatlabInfrastructureError("编译 Runtime 工程运行已取消")
                if timeout_seconds is not None and time.monotonic() - started > timeout_seconds:
                    _terminate_process_tree(process)
                    raise MatlabInfrastructureError("编译 Runtime 工程运行超时")
                time.sleep(0.05)
            reader.join(timeout=1)
            _drain_process_output(output_queue, log, console)
            publish_manifest_progress(output_dir, seen_iterations, progress)
        status = read_matlab_status(output_dir / "status.json")
        if process.returncode != 0 or status.get("state") != "completed":
            raise MatlabInfrastructureError(f"编译 Runtime 求解失败：{status.get('message', '未知错误')}")
        summary_path = output_dir / "result_summary.json"
        if not summary_path.is_file():
            raise MatlabInfrastructureError("编译 Runtime 未生成 result_summary.json")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise MatlabInfrastructureError("编译 Runtime result_summary.json 必须是对象")
        summary["status"] = "completed"
        summary["provenance"] = {"resultKind": "solver", "backend": "compiled-runtime", "lane": "compiled-runtime"}
        summary["files"] = [path.name for path in _result_files(output_dir)]
        return summary
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MatlabInfrastructureError(f"编译 Runtime 输出无效：{exc}") from exc
    finally:
        if process.poll() is None:
            _terminate_process_tree(process)
        _close_windows_process_job(process)
