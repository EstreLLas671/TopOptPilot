from __future__ import annotations

from pathlib import Path

from topoptpilot_desktop.engineering.runtime_discovery import (
    RuntimeInventory,
    discover_installed_runtimes,
)


def _runtime_layout(root: Path, *, version: str = "25.2.0") -> None:
    dll = root / "runtime" / "win64" / "mclmcrrt25_2.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"runtime")
    uninstaller = root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe"
    uninstaller.parent.mkdir(parents=True)
    uninstaller.write_bytes(b"uninstaller")
    (root / "VersionInfo.xml").write_text(
        f"<root><release>R2025b</release><version>{version}</version></root>",
        encoding="utf-8",
    )


def test_discovers_complete_runtime_from_a_standard_matlab_runtime_directory(tmp_path: Path) -> None:
    standard_base = tmp_path / "Program Files" / "MATLAB" / "MATLAB Runtime"
    runtime_root = standard_base / "R2025b"
    _runtime_layout(runtime_root)

    found = discover_installed_runtimes(registry_roots=[], standard_bases=[standard_base])

    assert [item.as_dict() for item in found] == [
        {
            "release": "R2025b",
            "version": "25.2.0",
            "path": str(runtime_root.resolve()),
            "source": "standard",
            "usable": True,
            "reason": "MATLAB Runtime 安装完整",
            "dllPath": str((runtime_root / "runtime" / "win64" / "mclmcrrt25_2.dll").resolve()),
            "uninstallerPath": str(
                (runtime_root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe").resolve()
            ),
        }
    ]


def test_requires_both_runtime_dll_and_runtime_uninstaller(tmp_path: Path) -> None:
    runtime_root = tmp_path / "MATLAB Runtime" / "R2025b"
    dll = runtime_root / "runtime" / "win64" / "mclmcrrt25_2.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"runtime")

    found = discover_installed_runtimes(
        registry_roots=[{"root": str(runtime_root), "release": "R2025b"}],
        standard_bases=[],
    )

    assert len(found) == 1
    assert found[0].usable is False
    assert found[0].reason == "缺少 MATLAB Runtime 卸载程序"


def test_full_matlab_installation_cannot_masquerade_as_runtime(tmp_path: Path) -> None:
    matlab_root = tmp_path / "MATLAB" / "R2025b"
    _runtime_layout(matlab_root)
    matlab = matlab_root / "bin" / "matlab.exe"
    matlab.write_bytes(b"matlab")

    found = discover_installed_runtimes(
        registry_roots=[{"root": str(matlab_root), "release": "R2025b"}],
        standard_bases=[],
    )

    assert len(found) == 1
    assert found[0].usable is False
    assert found[0].reason == "检测到完整 MATLAB，不能作为独立 MATLAB Runtime"


def test_registry_candidate_wins_when_the_same_runtime_is_also_in_a_standard_directory(
    tmp_path: Path,
) -> None:
    standard_base = tmp_path / "Program Files" / "MATLAB" / "MATLAB Runtime"
    runtime_root = standard_base / "R2025b"
    _runtime_layout(runtime_root)

    found = discover_installed_runtimes(
        registry_roots=[{"root": str(runtime_root), "release": "R2025b"}],
        standard_bases=[standard_base],
    )

    assert len(found) == 1
    assert found[0].source == "registry"


def test_runtime_inventory_can_be_initialized_and_refreshed_from_startup_or_health() -> None:
    calls = 0

    def discover():
        nonlocal calls
        calls += 1
        return []

    inventory = RuntimeInventory(discover=discover)

    assert inventory.initialized is False
    assert inventory.snapshot() == []
    assert inventory.initialized is True
    assert inventory.refresh() == []
    assert calls == 2
