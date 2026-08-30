from __future__ import annotations

from pathlib import Path

from topoptpilot_desktop.engineering.terminal import TerminalManager, default_bridge_script


def test_default_bridge_prefers_staged_desktop_resource(monkeypatch, tmp_path: Path) -> None:
    bridge = tmp_path / "matlab" / "engineering" / "topoptpilot_terminal_bridge.m"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("function topoptpilot_terminal_bridge(configPath)\nend", encoding="utf-8")
    monkeypatch.setenv("TOPPILOT_RESOURCE_ROOT", str(tmp_path))
    assert default_bridge_script() == bridge


def test_terminal_copies_default_bridge_when_matlab_is_started(monkeypatch, tmp_path: Path) -> None:
    resource_root = tmp_path / "resources"
    bridge = resource_root / "matlab" / "engineering" / "topoptpilot_terminal_bridge.m"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("function topoptpilot_terminal_bridge(configPath)\nend", encoding="utf-8")
    executable = tmp_path / "matlab.exe"
    executable.write_bytes(b"stub")
    monkeypatch.setenv("TOPPILOT_RESOURCE_ROOT", str(resource_root))

    class Child:
        def poll(self):
            return None

    monkeypatch.setattr("topoptpilot_desktop.engineering.terminal.subprocess.Popen", lambda *args, **kwargs: Child())
    manager = TerminalManager(tmp_path / "data")
    session = manager.start(project_root=tmp_path, executable=str(executable))
    copied = tmp_path / "data" / "sessions" / session["sessionId"] / "topoptpilot_terminal_bridge.m"
    assert copied.read_text(encoding="utf-8").startswith("function topoptpilot_terminal_bridge")


def test_terminal_manager_follows_shared_topoptpilot_data_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    assert TerminalManager().root == tmp_path.resolve() / "sessions"
