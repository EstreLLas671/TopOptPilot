from pathlib import Path
import shutil
import subprocess
import sys

import pytest


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


def test_desktop_sidecar_bundles_a_websocket_protocol_implementation() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "websockets>=" in requirements
    assert "--collect-submodules websockets" in script


def test_build_script_stages_matlab_mcp_solver_sources() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert '$SolverSource = Join-Path $ProjectRoot "求解器模块"' in script
    assert 'Copy-Item -LiteralPath $SolverSource -Destination (Join-Path $StageRoot "求解器模块") -Recurse' in script


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

def test_build_script_resolves_worktree_python_before_staging() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert '[string]$PythonExe = ""' in script
    assert "git -C $ProjectRoot rev-parse --git-common-dir" in script
    assert '".venv\\Scripts\\python.exe"' in script
    assert '& $PythonExe -c "import PyInstaller"' in script
    assert script.index('& $PythonExe -c "import PyInstaller"') < script.index("$StageRoot =")


def test_build_script_uses_transactional_staging_and_never_downloads_node() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert "$StageRoot =" in script
    assert "$BackupResourceRoot =" in script
    assert "Move-Item -LiteralPath $StageRoot -Destination $ResourceRoot" in script
    assert "Move-Item -LiteralPath $BackupResourceRoot -Destination $ResourceRoot" in script
    assert "curl.exe" not in script
    assert "node.exe is missing" in script


def test_standard_bundle_excludes_python_bytecode_caches() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    assert '$_.Extension -in @(".pyc", ".pyo")' in script
    assert '$_.Name -eq "__pycache__"' in script

def test_bundle_clears_stale_tauri_release_resources() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")

    release_resource = r'$ReleaseResourceRoot = Join-Path $DesktopRoot "src-tauri\target\release\resources"'
    assert release_resource in script
    assert 'Remove-Item -LiteralPath $ReleaseResourceRoot -Recurse -Force' in script
    assert script.index(release_resource) < script.index("npm --prefix $DesktopRoot run tauri build")

def test_all_formal_inputs_are_checked_before_transactional_staging() -> None:
    script = (ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8")
    stage_index = script.index("$StageRoot =")

    for marker in (
        "$SidecarSource",
        "$MatlabSource",
        "$McpSource",
        "$SolverSource",
        "$PiSource",
        "$NodeExecutable",
        "$MatlabMcpExecutable",
        "$RootNodeModules",
        "$PackageJson",
        "$PackageLock",
    ):
        assert script.index(marker) < stage_index

def test_failed_preflight_preserves_existing_resource_staging(tmp_path: Path) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is required for the Windows build contract")
    project = tmp_path / "project"
    scripts = project / "scripts"
    resources = project / "desktop" / "src-tauri" / "resources"
    scripts.mkdir(parents=True)
    resources.mkdir(parents=True)
    script = scripts / "build_desktop.ps1"
    script.write_text((ROOT / "scripts" / "build_desktop.ps1").read_text(encoding="utf-8"), encoding="utf-8")
    sentinel = resources / "sentinel.txt"
    sentinel.write_text("preserve-me", encoding="utf-8")

    completed = subprocess.run(
        [shell, "-NoProfile", "-File", str(script), "-SkipInstall", "-SkipSidecar", "-SkipBundle", "-PythonExe", sys.executable],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert completed.returncode != 0
    assert sentinel.read_text(encoding="utf-8") == "preserve-me"
    assert list(resources.iterdir()) == [sentinel]
