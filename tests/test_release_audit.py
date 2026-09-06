from __future__ import annotations

import pytest

from topoptpilot import release_audit
from topoptpilot.service import research_service


STANDARD_RESOURCE_FILES = (
    "bin/topoptpilot-backend.exe",
    "node/node.exe",
    "vendor/matlab-mcp-server/matlab-mcp-server-windows-x64.exe",
    "mcp/matlab_mcp/topopt-tools.json",
    "求解器模块/2D/TopOpt_integrated/TopOpt_integrated/topopt_main.m",
    "求解器模块/TopOpt-3D/TopOpt-3D/topopt3d_main.m",
)


def _write_standard_resources(root) -> None:
    resources = root / "desktop/src-tauri/target/release/resources"
    for relative in STANDARD_RESOURCE_FILES:
        path = resources / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"resource")


def test_desktop_gate_reports_topoptpilot_executable_and_installer_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(release_audit, "ROOT", tmp_path)
    executable = tmp_path / "desktop/src-tauri/target/release/topoptpilot.exe"
    installer = tmp_path / "desktop/src-tauri/target/release/bundle/nsis/TopOptPilot_2.1.3_x64-setup.exe"
    executable.parent.mkdir(parents=True)
    installer.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    installer.write_bytes(b"installer")
    _write_standard_resources(tmp_path)

    result = release_audit._desktop_gate()

    assert result["pass"] is True
    assert result["executable"].endswith("topoptpilot.exe")
    assert result["installer"].endswith("TopOptPilot_2.1.3_x64-setup.exe")
def test_cases_gate_requires_real_matlab_mcp_f3() -> None:
    cases = {
        "A": {"metrics": {"best_feasible_objective": 1.0}},
        "B": {"experiments": 6},
        "C": {"fidelities": ["STEP1", "STEP2", "STEP3", "STEP4"], "real_backends": ["python", "matlab_mcp_3d"]},
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
    monkeypatch.setattr(release_audit, "_strict_step4_gate", lambda: {"pass": True})
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
    assert gates["evaluator_first"]["pass"] is True
    assert gates["fidelity_lane_mapping"]["pass"] is True
    assert gates["fact_grounded_reports"]["pass"] is True
    assert gates["credential_not_in_sqlite"]["pass"] is True

def test_desktop_gate_rejects_missing_standard_resources_and_runtime_payload(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(release_audit, "ROOT", tmp_path)
    executable = tmp_path / "desktop/src-tauri/target/release/topoptpilot.exe"
    installer = tmp_path / "desktop/src-tauri/target/release/bundle/nsis/TopOptPilot_2.1.3_x64-setup.exe"
    executable.parent.mkdir(parents=True)
    installer.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    installer.write_bytes(b"installer")
    _write_standard_resources(tmp_path)
    (tmp_path / "desktop/src-tauri/target/release/resources/node/node.exe").unlink()

    missing = release_audit._desktop_gate()
    assert missing["pass"] is False
    assert "node/node.exe" in missing["missing_resources"]

    _write_standard_resources(tmp_path)
    runtime = tmp_path / "desktop/src-tauri/target/release/resources/runtime/runtime-manifest.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("{}", encoding="utf-8")
    mixed = release_audit._desktop_gate()
    assert mixed["pass"] is False
    assert mixed["runtime_in_standard_package"] is True


def test_desktop_gate_accepts_tauri_resource_contract_without_release_copy(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(release_audit, "ROOT", tmp_path)
    executable = tmp_path / "desktop/src-tauri/target/release/topoptpilot.exe"
    installer = tmp_path / "desktop/src-tauri/target/release/bundle/nsis/TopOptPilot_2.1.3_x64-setup.exe"
    executable.parent.mkdir(parents=True)
    installer.parent.mkdir(parents=True)
    executable.write_bytes(b"exe")
    installer.write_bytes(b"installer")
    resources = tmp_path / "desktop/src-tauri/resources"
    for relative in STANDARD_RESOURCE_FILES:
        path = resources / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"resource")
    config = tmp_path / "desktop/src-tauri/tauri.conf.json"
    config.write_text('{"bundle":{"resources":["resources/**/*"]}}', encoding="utf-8")

    result = release_audit._desktop_gate()

    assert result["pass"] is True
    assert result["resource_contract"] is True
    assert result["resource_root"].endswith("desktop\\src-tauri\\resources")

