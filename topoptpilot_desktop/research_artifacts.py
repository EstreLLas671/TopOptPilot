"""Adapt TopOptPilot experiment outputs to the shared artifact viewer contract."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _file_ref(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    root = root.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact path is outside research data root: {resolved}") from exc
    if not resolved.is_file():
        raise ValueError(f"artifact file does not exist: {resolved}")
    return {
        "relativePath": relative,
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        "mediaType": "application/octet-stream",
        "sizeBytes": resolved.stat().st_size,
    }


def build_research_artifact_index(research: dict[str, Any], data_root: Path) -> dict[str, Any]:
    root = Path(data_root).resolve()
    experiments: list[dict[str, Any]] = []
    for experiment in research.get("experiments", []):
        result = experiment.get("result") or {}
        artifacts = result.get("artifacts") or {}
        refs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in artifacts.values():
            if not isinstance(raw, str) or not raw:
                continue
            path = Path(raw)
            if path.exists():
                ref = _file_ref(path, root)
                if ref["relativePath"] not in seen:
                    refs.append(ref)
                    seen.add(ref["relativePath"])
        experiments.append({
            "experimentId": experiment.get("id", ""),
            "status": experiment.get("status", ""),
            "fidelity": experiment.get("fidelity", ""),
            "backend": experiment.get("backend", ""),
            "provenance": {"ownerType": "research-experiment", "backend": experiment.get("backend", "unknown"), "fidelity": experiment.get("fidelity", "")},
            "files": refs,
            "metrics": {
                "compliance": (result.get("objective") or {}).get("compliance"),
                "grayRatio": (result.get("quality") or {}).get("gray_ratio"),
            },
        })
    return {"researchId": research.get("id", ""), "experiments": experiments}
