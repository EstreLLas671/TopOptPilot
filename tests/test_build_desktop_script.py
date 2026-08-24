from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_build_script_uses_project_python_and_rejects_stale_sidecar_success() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert '".venv\\Scripts\\python.exe"' in script
    assert "& $PythonExe -m PyInstaller" in script
    assert 'throw "PyInstaller failed with exit code $LASTEXITCODE."' in script
    assert "Remove-Item -LiteralPath $BackendExecutable -Force" in script


def test_build_script_checks_dependency_install_exit_codes() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert 'throw "Python dependency installation failed with exit code $LASTEXITCODE."' in script
    assert 'throw "npm install failed with exit code $LASTEXITCODE."' in script


def test_build_script_exposes_explicit_runtime_package_staging() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert "[switch]$RuntimePackage" in script
    assert "[string]$RuntimeRoot" in script
    assert "[string]$RuntimeSolver" in script
    assert "mclmcrrt*.dll" in script
    assert "runtime-manifest.json" in script
    assert "RuntimePackage requires -RuntimeRoot" in script
    assert "Uninstall_MATLAB_Runtime.exe" in script
    assert "standalone MATLAB Runtime" in script


def test_standard_bundle_removes_local_matlab_compiler_outputs() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert '$StagedMatlabDist = Join-Path $StagedMatlabRoot "dist"' in script
    assert "Remove-Item -LiteralPath $StagedMatlabDist -Recurse -Force" in script
    assert 'solver = "runtime/solver/TopOptSolver.exe"' in script
