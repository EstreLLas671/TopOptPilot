from __future__ import annotations

from fastapi.testclient import TestClient

from topoptpilot_desktop.api.app import app


def test_engineering_health_reports_unprobed_capabilities() -> None:
    response = TestClient(app).get("/api/engineering/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "engineering"
    assert payload["version"] == "2.0.3"
    assert payload["capabilities"] == {
        "localMatlab": "unprobed",
        "compiledRuntime": "optional",
    }
    assert payload["python"]["mode"] in {"source", "packaged"}
    assert payload["python"]["version"]
    assert payload["python"]["bundled"] is (payload["python"]["mode"] == "packaged")


def test_engineering_health_uses_the_existing_desktop_token_guard(monkeypatch) -> None:
    monkeypatch.setenv("TOPPILOT_DESKTOP_TOKEN", "desktop-secret")
    client = TestClient(app)

    denied = client.get("/api/engineering/health")
    allowed = client.get(
        "/api/engineering/health",
        headers={"x-topoptpilot-token": "desktop-secret"},
    )

    assert denied.status_code == 401
    assert allowed.status_code == 200

def test_engineering_matlab_installations_expose_only_verified_files(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TOPOPTPILOT_MATLAB_PATH", str(tmp_path / "missing"))
    response = TestClient(app).get(
        "/api/engineering/matlab/installations",
        headers={"x-topoptpilot-token": ""},
    )

    assert response.status_code == 200
    installations = response.json()["installations"]
    assert all(item["executable"].lower() != str(tmp_path / "missing").lower() for item in installations)
    assert all(item["probeState"] == "unknown" for item in installations)


def test_engineering_preference_rejects_research_matlab_lane() -> None:
    response = TestClient(app).post(
        "/api/engineering/matlab/preference",
        json={"preference": "matlab-mcp"},
    )

    assert response.status_code == 422

def test_runtime_probe_requires_solver_and_returns_verified_profile(monkeypatch, tmp_path) -> None:
    runtime_root = tmp_path / "runtime" / "R2025b"
    dll = runtime_root / "runtime" / "win64" / "mclmcrrt25_2.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"dll")
    uninstaller = runtime_root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe"
    uninstaller.parent.mkdir(parents=True)
    uninstaller.write_bytes(b"uninstaller")
    solver = tmp_path / "app" / "solver" / "TopOptSolver.exe"
    solver.parent.mkdir(parents=True)
    solver.write_bytes(b"solver")
    monkeypatch.setenv("TOPOPTPILOT_RUNTIME_SOLVER_ALLOWLIST", str(solver))
    client = TestClient(app)

    root_only = client.post("/api/engineering/runtime/probe", json={"root": str(runtime_root)})
    verified = client.post(
        "/api/engineering/runtime/probe",
        json={"root": str(runtime_root), "solverExecutable": str(solver)},
    )

    assert root_only.status_code == 422
    assert verified.status_code == 200
    assert verified.json() == {
        "state": "ready",
        "root": str(runtime_root.resolve()),
        "dllPath": str(dll.resolve()),
        "solverExecutable": str(solver.resolve()),
        "profileId": verified.json()["profileId"],
        "usable": True,
        "diagnostic": "Runtime 与编译求解器已验证",
    }


def test_compiled_runtime_run_rejects_direct_executable_injection(tmp_path) -> None:
    solver = tmp_path / "arbitrary.exe"
    solver.write_bytes(b"arbitrary")
    response = TestClient(app).post(
        "/api/engineering/runs",
        json={
            "lane": "compiled-runtime",
            "ownerId": "injection-test",
            "runtimeRoot": str(tmp_path),
            "solverExecutable": str(solver),
            "task": {},
        },
    )

    assert response.status_code == 422


def test_bundled_runtime_endpoint_reports_standard_package_without_prompting(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TOPPILOT_RESOURCE_ROOT", str(tmp_path))

    response = TestClient(app).get("/api/engineering/runtime/bundled")

    assert response.status_code == 200
    assert response.json() == {
        "state": "unavailable",
        "usable": False,
        "profileId": None,
        "diagnostic": "当前为标准版，未捆绑 MATLAB Runtime",
    }
