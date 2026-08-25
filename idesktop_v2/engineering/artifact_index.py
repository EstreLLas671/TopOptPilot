"""Deterministic indexing for engineering run outputs."""

from __future__ import annotations

from pathlib import Path


def media_type_for(path: Path) -> str:
    return {
        ".json": "application/json",
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".log": "text/plain",
        ".txt": "text/plain",
        ".mat": "application/vnd.mathworks.matlab.mat",
        ".bin": "application/vnd.idesktop.float32",
        ".png": "image/png",
    }.get(path.suffix.lower(), "application/octet-stream")


def discover_artifact_files(run_dir: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    snapshots: list[Path] = []
    for path in sorted(run_dir.rglob("*"), key=lambda item: item.relative_to(run_dir).as_posix()):
        if not path.is_file() or path.name.endswith(".tmp") or path.name == "run-manifest.json":
            continue
        relative = path.relative_to(run_dir)
        (snapshots if relative.parts and relative.parts[0] == "snapshots" else files).append(path)
    return files, snapshots
