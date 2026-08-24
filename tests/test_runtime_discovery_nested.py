from pathlib import Path

from idesktop_v2.engineering.runtime_discovery import discover_installed_runtimes


def test_standard_release_wrapper_resolves_the_single_complete_nested_runtime(tmp_path: Path) -> None:
    standard_base = tmp_path / "Program Files" / "MATLAB" / "MATLAB Runtime"
    wrapper = standard_base / "R2025b"
    runtime_root = wrapper / "R2025b"
    dll = runtime_root / "runtime" / "win64" / "mclmcrrt25_2.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"runtime")
    uninstaller = runtime_root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe"
    uninstaller.parent.mkdir(parents=True)
    uninstaller.write_bytes(b"uninstaller")
    (runtime_root / "VersionInfo.xml").write_text(
        "<root><release>R2025b</release><version>25.2.0</version></root>",
        encoding="utf-8",
    )

    found = discover_installed_runtimes(registry_roots=[], standard_bases=[standard_base])

    assert len(found) == 1
    assert found[0].path == runtime_root.resolve()
    assert found[0].usable is True
