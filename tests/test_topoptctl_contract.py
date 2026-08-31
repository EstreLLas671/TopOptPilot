"""Contract tests for the headless, policy-bounded ``topoptctl`` surface.

These tests deliberately exercise the command core without starting MATLAB or
an LLM.  The end-to-end tests use the same public HTTP contract separately.
"""

from __future__ import annotations

import json
import io
from pathlib import Path

import pytest
from pydantic import ValidationError

import topoptpilot.cli as topopt_cli
from topoptpilot.cli import (
    CliEngineeringTask,
    HeadlessSession,
    HttpApiClient,
    build_engineering_request,
    collect_doctor_report,
    parse_sidecar_banner,
    propose_policy_intent,
    redact_for_output,
    render_output,
    session_public_payload,
)


def _tiny_2d_task() -> dict:
    return {
        "dimension": "2d",
        "load_case": "cantilever",
        "geometry": {"nelx": 20, "nely": 10},
        "params": {
            "volfrac": 0.4,
            "penal": 3.0,
            "rmin": 1.5,
            "min_iter": 1,
            "max_iter": 2,
            "filter_strategy": "fixed",
            "accuracy": "standard",
        },
        "material": {"preset": "normalized", "name": "归一化参考材料"},
    }


def test_cli_task_is_strict_and_never_accepts_raw_matlab_or_paths() -> None:
    task = CliEngineeringTask.model_validate(_tiny_2d_task())
    request = build_engineering_request(task, owner_id="topoptctl:project-1")
    assert request["lane"] == "local-matlab"
    assert request["task"]["dimension"] == "2d"
    assert request["task"]["geometry"] == {"nelx": 20, "nely": 10}

    for forbidden in (
        {"matlab": "delete('*')"},
        {"matlab_command": "run('anything')"},
        {"output_directory": "C:/outside"},
    ):
        with pytest.raises(ValidationError):
            CliEngineeringTask.model_validate(_tiny_2d_task() | forbidden)

    with pytest.raises(ValidationError):
        CliEngineeringTask.model_validate(
            _tiny_2d_task() | {"geometry": {"nelx": 20, "nely": 10, "path": ".."}}
        )


def test_sidecar_banner_and_persisted_session_never_serialize_token(tmp_path: Path) -> None:
    parsed = parse_sidecar_banner(
        'TOPPILOT_SIDECAR={"port": 43123, "token": "private-session-token-0123456789abcdef"}'
    )
    assert parsed["port"] == 43123
    assert parsed["token"] == "private-session-token-0123456789abcdef"

    session = HeadlessSession(
        session_id="headless-1234",
        pid=12345,
        port=43123,
        data_dir=tmp_path,
        started_at="2026-08-30T00:00:00+00:00",
    )
    public = session_public_payload(session)
    serialized = json.dumps(public, ensure_ascii=False)
    assert "token" not in serialized.lower()
    assert public["sessionId"] == "headless-1234"


class _RecordingClient(HttpApiClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def request_json(self, method: str, path: str, payload: dict | None = None):
        self.calls.append((method, path, payload))
        if path == "/api/tools/invoke" and payload and payload["tool"] == "policy_compile_intent":
            return {"ok": True, "result": [{"id": "P-1"}]}
        return {"ok": True, "result": {"context": "authoritative"}}


def test_policy_proposal_always_refreshes_context_before_compiling_intent() -> None:
    client = _RecordingClient()
    result = propose_policy_intent(
        client,
        research_id="R-1",
        intent="ESTABLISH_BASELINE",
        preserve=[],
        factor=None,
        source_experiment=None,
    )
    assert result["result"][0]["id"] == "P-1"
    assert [call[2]["tool"] for call in client.calls] == [
        "research_get_context",
        "policy_compile_intent",
    ]
    assert client.calls[1][2]["source"] == "TOPoptctl"


def test_output_redaction_removes_credentials_but_preserves_real_metrics() -> None:
    safe = redact_for_output({
        "api_key": "secret", "nested": {"token": "another-secret"},
        "metrics": {"compliance": 12.5, "iterations": 2},
    })
    assert safe["api_key"] == "[REDACTED]"
    assert safe["nested"]["token"] == "[REDACTED]"
    assert safe["metrics"] == {"compliance": 12.5, "iterations": 2}


def test_machine_json_envelope_uses_ascii_escapes_for_cross_code_page_paths() -> None:
    encoded = render_output({"path": "D:/项目/拓扑挑战杯"}, json_output=True)
    assert "\\u9879\\u76ee" in encoded
    assert json.loads(encoded)["path"] == "D:/项目/拓扑挑战杯"


class _DoctorClient(HttpApiClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def request_json(self, method: str, path: str, payload: dict | None = None):
        self.calls.append((method, path, payload))
        if path == "/api/settings":
            return {
                "agent": {
                    "model": "qwen-example",
                    "base_url": "https://example.invalid/compatible-mode/v1",
                    "safe_mode": True,
                },
                "compute": {"matlab_root": "C:/MATLAB", "matlab_timeout_seconds": 300},
                "api_key_status": "credential_manager",
                "api_key": "must-not-leak",
            }
        if path == "/api/settings/test-agent":
            return {"ok": True, "status": "verified", "model": "qwen-example"}
        return {"status": "ok", "path": path}


def _doctor_session(tmp_path: Path) -> HeadlessSession:
    return HeadlessSession(
        session_id="headless-doctor",
        pid=12345,
        port=43123,
        data_dir=tmp_path,
        started_at="2026-08-30T00:00:00+00:00",
    )


def test_doctor_is_read_only_without_explicit_external_checks(tmp_path: Path) -> None:
    client = _DoctorClient()
    report = collect_doctor_report(
        client,
        _doctor_session(tmp_path),
        probe_matlab=False,
        check_qwen=False,
    )

    assert report["sideEffect"] == "none"
    assert report["performed"] == []
    assert report["qwen"]["status"] == "not-checked"
    assert [(method, path) for method, path, _ in client.calls] == [
        ("GET", "/api/health"),
        ("GET", "/api/settings"),
        ("GET", "/api/engineering/health"),
        ("GET", "/api/engineering/environment"),
    ]
    safe = redact_for_output(report)
    assert safe["settings"]["agent"]["credentialSource"] == "credential_manager"
    assert "api_key" not in safe["settings"]


def test_doctor_only_probes_external_dependencies_when_explicit(tmp_path: Path) -> None:
    client = _DoctorClient()
    report = collect_doctor_report(
        client,
        _doctor_session(tmp_path),
        probe_matlab=True,
        check_qwen=True,
    )

    assert report["sideEffect"] == "external-probes"
    assert report["performed"] == ["matlab-discovery-probe", "qwen-connection-check"]
    assert [(method, path) for method, path, _ in client.calls][-2:] == [
        ("POST", "/api/engineering/environment/refresh"),
        ("POST", "/api/settings/test-agent"),
    ]


def test_qwen_key_command_accepts_only_stdin_and_never_echoes_secret(monkeypatch, tmp_path: Path, capsys) -> None:
    stored: list[str] = []
    monkeypatch.setattr(topopt_cli, "set_qwen_api_key", stored.append)
    monkeypatch.setattr(topopt_cli, "qwen_api_key_source", lambda: "credential_manager")

    without_stdin = topopt_cli.main([
        "--data-dir", str(tmp_path), "configure", "qwen-key",
    ])
    without_output = capsys.readouterr().out
    assert without_stdin == 2
    assert "SECRET_INPUT_REQUIRED" in without_output

    secret = "qwen-test-credential-value-0123456789"
    monkeypatch.setattr(topopt_cli.sys, "stdin", io.StringIO(secret + "\n"))
    with_stdin = topopt_cli.main([
        "--data-dir", str(tmp_path), "configure", "qwen-key", "--stdin",
    ])
    with_output = capsys.readouterr().out
    assert with_stdin == 0
    assert stored == [secret]
    assert secret not in with_output
    assert "credential_manager" in with_output
