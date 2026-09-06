"""TopOptPilot launcher. The primary product entry is the native Tauri app."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def check_environment(web: bool = False) -> list[str]:
    required = ["fastapi", "pydantic", "numpy", "scipy", "matplotlib", "uvicorn"]
    if web:
        required.append("streamlit")
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
    parser = argparse.ArgumentParser(description="Launch the native TopOptPilot desktop app")
    parser.add_argument("--web", action="store_true", help="run the legacy Streamlit developer UI")
    args = parser.parse_args()
    missing = check_environment(args.web)
    if missing:
        print("Missing dependencies: " + ", ".join(missing))
        print(f"Install with: {sys.executable} -m pip install -r requirements.txt")
        return 2
    check_solver()
    check_pi()
    if args.web:
        print("Starting the development-only Streamlit workspace.")
        command = [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
                   "--server.headless=false", "--browser.gatherUsageStats=false"]
        return subprocess.call(command, cwd=ROOT)
    installed = ROOT / "desktop/src-tauri/target/release/topoptpilot-desktop.exe"
    if installed.exists():
        return subprocess.call([str(installed)], cwd=installed.parent)
    if not (ROOT / "desktop/node_modules/@tauri-apps/cli").exists():
        print("Desktop dependencies are missing. Run: npm --prefix desktop install")
        return 2
    print("TopOptPilot native desktop development environment: READY")
    command = ["npm.cmd" if sys.platform == "win32" else "npm", "--prefix", "desktop",
               "run", "tauri", "dev"]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
