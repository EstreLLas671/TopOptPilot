from __future__ import annotations

import pytest

from topoptpilot_desktop.engineering.terminal import MAX_COMMAND_BYTES, TerminalManager


def test_terminal_session_queues_utf8_command_atomically(tmp_path) -> None:
    manager = TerminalManager(tmp_path)
    session = manager.start(project_root=tmp_path)
    queued = manager.command(session["sessionId"], "disp('hello')")
    assert queued["id"] == 1
    command_file = tmp_path / "sessions" / session["sessionId"] / "commands" / "command_00000001.json"
    assert command_file.exists()
    assert manager.poll(session["sessionId"])["results"] == []


def test_terminal_rejects_empty_invalid_and_oversized_commands(tmp_path) -> None:
    manager = TerminalManager(tmp_path)
    session = manager.start(project_root=tmp_path)
    with pytest.raises(ValueError, match="不能为空"):
        manager.command(session["sessionId"], "  ")
    with pytest.raises(ValueError, match="过长"):
        manager.command(session["sessionId"], "x" * (MAX_COMMAND_BYTES + 1))
    with pytest.raises(KeyError):
        manager.command("missing", "disp(1)")


def test_terminal_stop_marks_session_stopped(tmp_path) -> None:
    manager = TerminalManager(tmp_path)
    session = manager.start(project_root=tmp_path)
    stopped = manager.stop(session["sessionId"])
    assert stopped["status"] == "stopped"
