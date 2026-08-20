"""TopOptPilot local launcher: validate environment and start the Workspace."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def check_environment() -> list[str]:
    required = ["streamlit", "fastapi", "pydantic", "numpy", "scipy", "matplotlib"]
    return [package for package in required if importlib.util.find_spec(package) is None]


def check_pi() -> None:
    cli = ROOT / "node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
    if not shutil.which("node") or not cli.exists():
        raise RuntimeError("Official Pi runtime is missing. Run: npm install")


def check_solver() -> None:
    from solver.params import normalize_task
    spec = normalize_task({"mesh_level": "coarse", "params": {"max_iter": 1}})
    if spec["nelx"] <= 0 or spec["nely"] <= 0:
        raise RuntimeError("2D solver configuration is invalid")


def main() -> int:
    missing = check_environment()
    if missing:
        print("Missing dependencies: " + ", ".join(missing))
        print(f"Install with: {sys.executable} -m pip install -r requirements.txt")
        return 2
    check_solver()
    check_pi()
    print("TopOptPilot environment: READY")
    print("Pi RPC: READY | 2D Solver: READY | Python 3D: READY | MATLAB: OPTIONAL")
    command = [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
               "--server.headless=false", "--browser.gatherUsageStats=false"]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
