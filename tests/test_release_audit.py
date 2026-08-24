from __future__ import annotations

import pytest

from topoptpilot import release_audit
from topoptpilot.service import research_service


def test_desktop_gate_reports_v2_executable_and_installer_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(release_audit, "ROOT", tmp_path)
    executable = tmp_path / "desktop/src-tauri/target/release/idesktop-v2.exe"
    installer = tmp_path / "desktop/src-tauri/target/release/bundle/nsis/iDeskTop-v2_2.0.0_x64-setup.exe"
    executable.parent.mkdir(parents=True)
    installer.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    installer.write_bytes(b"installer")

    result = release_audit._desktop_gate()

    assert result["pass"] is True
    assert result["executable"].endswith("idesktop-v2.exe")
    assert result["installer"].endswith("iDeskTop-v2_2.0.0_x64-setup.exe")
def test_desktop_gate_accepts_tauri_product_name_with_space(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(release_audit, "ROOT", tmp_path)
    executable = tmp_path / "desktop/src-tauri/target/release/idesktop-v2.exe"
    installer = tmp_path / "desktop/src-tauri/target/release/bundle/nsis/iDeskTop v2_2.0.0_x64-setup.exe"
    executable.parent.mkdir(parents=True)
    installer.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    installer.write_bytes(b"installer")

    result = release_audit._desktop_gate()

    assert result["pass"] is True
    assert result["installer"].endswith("iDeskTop v2_2.0.0_x64-setup.exe")
def test_cases_gate_requires_real_matlab_mcp_f3() -> None:
    cases = {
        "A": {"metrics": {"best_feasible_objective": 1.0}},
        "B": {"experiments": 6},
        "C": {"fidelities": ["F0", "F1", "F2", "F3"], "real_backends": ["python", "matlab_mcp_3d"]},
    }

    assert release_audit._cases_gate_passes(cases) is True
    cases["C"]["real_backends"] = ["python", "python3d"]
    assert release_audit._cases_gate_passes(cases) is False


def test_research_service_can_disable_pi_for_offline_work(monkeypatch, tmp_path) -> None:
    def fail_if_started(_service):
        raise AssertionError("PiBridge must not start during offline work")

    monkeypatch.setattr(research_service, "PiBridge", fail_if_started)
    service = research_service.ResearchService(
        tmp_path / "offline-state",
        max_workers=1,
        enable_agent_runtime=False,
    )
    try:
        assert service.pi_runtime is None
        assert service.pi_runtime_error == "disabled"
    finally:
        service.close()


def test_offline_release_audit_disables_agent_runtime(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class StopAudit(RuntimeError):
        pass

    def capture_service(*_args, **kwargs):
        observed.update(kwargs)
        raise StopAudit

    monkeypatch.setattr(release_audit, "_artifact_gate", lambda: {"pass": True})
    monkeypatch.setattr(release_audit, "_desktop_gate", lambda: {"pass": True})
    monkeypatch.setattr(release_audit, "_strict_f3_gate", lambda: {"pass": True})
    monkeypatch.setattr(release_audit, "_i18n_gate", lambda: {"pass": True})
    monkeypatch.setattr(release_audit, "_v6_source_gates", lambda: {})
    monkeypatch.setattr(release_audit, "_matlab_mcp_gates", lambda: {})
    monkeypatch.setattr(release_audit, "ResearchService", capture_service)

    with pytest.raises(StopAudit):
        release_audit.run_audit(include_online=False)

    assert observed["enable_agent_runtime"] is False


def test_source_gates_match_v2_lanes_and_grounded_reports() -> None:
    gates = release_audit._v6_source_gates()

    assert "all_matlab_fidelities" not in gates
    assert gates["fidelity_lane_mapping"]["pass"] is True
    assert gates["fact_grounded_reports"]["pass"] is True
