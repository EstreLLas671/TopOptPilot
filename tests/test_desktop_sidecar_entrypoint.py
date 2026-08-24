from __future__ import annotations

import multiprocessing

from idesktop_v2.api import desktop_sidecar


def test_desktop_entrypoint_dispatches_frozen_workers_before_starting_server(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(multiprocessing, "freeze_support", lambda: calls.append("freeze_support"))
    monkeypatch.setattr(desktop_sidecar, "main", lambda: calls.append("main") or 17)

    assert desktop_sidecar.run_entrypoint() == 17
    assert calls == ["freeze_support", "main"]
