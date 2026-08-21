"""Executable V5 release gates. Run: python -m topoptpilot.release_audit"""

from __future__ import annotations

import json
import argparse
import tempfile
import time
from pathlib import Path

from topoptpilot.benchmarks import BenchmarkRunner
from topoptpilot.cases import EvidenceCaseRunner
from topoptpilot.service import ResearchService
from topoptpilot.tools import ALLOWED_TOOLS
from mcp.matlab_mcp import MatlabMcpWorker
from solver.matlab3d_adapter import run_matlab3d_or_replay


ROOT = Path(__file__).resolve().parents[1]


def run_audit(include_online: bool = True) -> dict:
    report = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "gates": {}}
    report["gates"]["artifacts"] = _artifact_gate()
    report["gates"]["desktop_app"] = _desktop_gate()
    report["gates"]["strict_f3"] = _strict_f3_gate()
    report["gates"]["i18n_zh_default"] = _i18n_gate()
    report["gates"].update(_matlab_mcp_gates())
    with tempfile.TemporaryDirectory(prefix="topoptpilot_release_") as directory:
        service = ResearchService(directory, max_workers=2)
        try:
            cases = EvidenceCaseRunner(service, timeout=240)
            report["cases"] = {}
            for case_id in "ABC":
                result = cases.run(case_id)
                report["cases"][case_id] = {
                    "research_id": result["research_id"], "experiments": len(result["experiments"]),
                    "fidelities": [item["fidelity"].split()[0] for item in result["experiments"]],
                    "metrics": result["metrics"],
                    "real_backends": [item["result"]["solver"]["backend"]
                                      for item in result["experiments"] if item.get("result")],
                }
            report["gates"]["cases"] = {
                "pass": (report["cases"]["A"]["metrics"]["best_feasible_objective"] is not None
                         and report["cases"]["B"]["experiments"] >= 6
                         and report["cases"]["C"]["fidelities"][-4:] == ["F0", "F1", "F2", "F3"]
                         and any("python3d" in value for value in report["cases"]["C"]["real_backends"])),
            }
            runner = BenchmarkRunner()
            report["baselines"] = {method: runner.run(method, budget=5, max_iter=40)["metrics"]
                                   for method in ("Random", "Grid", "TPE", "Rule")}
            report["gates"]["baselines"] = {"pass": (
                set(report["baselines"]) == {"Random", "Grid", "TPE", "Rule"}
                and all(value["total_fem_cost"] == 5 for value in report["baselines"].values())
                and all(value["best_compliance"] is not None
                        for value in report["baselines"].values()))}
            report["safe_mode"] = _safe_mode_gate(service)
            report["gates"]["safe_mode"] = {"pass": report["safe_mode"]["pass"]}
            report["online_qwen"] = _online_gate(service) if include_online else {"pass": None, "skipped": True}
            report["gates"]["online_qwen"] = {"pass": report["online_qwen"].get("pass")}
        finally:
            service.close()
    required = [value["pass"] for key, value in report["gates"].items() if key != "online_qwen"]
    report["offline_release_ready"] = all(required)
    report["release_ready"] = report["offline_release_ready"] and report["online_qwen"].get("pass") is True
    return report


def _artifact_gate() -> dict:
    skills = list((ROOT / ".pi/skills").glob("*/SKILL.md"))
    extension = (ROOT / ".pi/extensions/topopt-tools.ts").read_text(encoding="utf-8")
    return {"pass": len(skills) == 6 and all(name in extension for name in ALLOWED_TOOLS),
            "skills": len(skills), "tools": len(ALLOWED_TOOLS),
            "agents_constitution": (ROOT / "AGENTS.md").exists()}


def _desktop_gate() -> dict:
    executable = ROOT / "desktop/src-tauri/target/release/topoptpilot-desktop.exe"
    installer = ROOT / "desktop/src-tauri/target/release/bundle/nsis/TopOptPilot_5.1.1_x64-setup.exe"
    return {"pass": executable.exists() and installer.exists(),
            "executable": str(executable), "installer": str(installer)}


def _strict_f3_gate() -> dict:
    try:
        run_matlab3d_or_replay({"mesh_level": "fine3d", "params": {"grid3d": [4, 2, 2]}})
    except RuntimeError as exc:
        return {"pass": "fallback is forbidden" in str(exc), "evidence": str(exc)}
    return {"pass": False, "evidence": "legacy F3 adapter returned a result"}


def _i18n_gate() -> dict:
    source = (ROOT / "desktop/src/i18n.ts").read_text(encoding="utf-8")
    models = (ROOT / "topoptpilot/schemas/models.py").read_text(encoding="utf-8")
    passed = ('"zh-CN"' in source and '"en-US"' in source
              and 'fallbackLng: "zh-CN"' in source and 'locale: str = "zh-CN"' in models)
    return {"pass": passed, "default": "zh-CN", "locales": ["zh-CN", "en-US"]}


def _matlab_mcp_gates() -> dict:
    output = {}
    with tempfile.TemporaryDirectory(prefix="topoptpilot_matlab_gate_") as directory:
        worker = MatlabMcpWorker(directory, ROOT)
        try:
            common = {"load_case": "cantilever", "projection": "heaviside_projection",
                      "params": {"volfrac": .4, "penal": 3, "rmin": 1.5, "max_iter": 2}}
            for dimension, mesh, grid in ((2, "coarse", None), (3, "coarse3d", [4, 2, 2])):
                task = {**common, "task_id": f"audit-{dimension}d", "mesh_level": mesh,
                        "params": {**common["params"]}}
                if grid:
                    task["params"]["grid3d"] = grid
                key = f"matlab_mcp_{dimension}d"
                try:
                    result = worker.run(task, "AUDIT", f"E{dimension}D")
                    solver = result["solver"]
                    output[key] = {"pass": solver["backend"] == key,
                                   "backend": solver["backend"],
                                   "matlab_version": solver.get("matlab_version"),
                                   "mcp_version": solver.get("mcp_version"),
                                   "solver_entry_sha256": solver.get("solver_entry_sha256")}
                except Exception as exc:
                    output[key] = {"pass": False, "error": str(exc)[:500]}
        finally:
            worker.close()
    return output


def _safe_mode_gate(service: ResearchService) -> dict:
    research = service.create_research({"name": "Safe mode gate", "mode": "AUTONOMOUS",
        "budget_total": 2, "budgets": {"total": 2, "f0": 2, "f1": 0, "f2": 0, "f3": 0}})
    service.start_autonomous_research(research["id"])
    deadline = time.time() + 90
    while time.time() < deadline:
        state = service.get_research(research["id"])
        if state.get("termination_reason"): break
        time.sleep(.2)
    intents = [item["intent"] for item in state["experiments"]]
    residuals = [(item.get("result") or {}).get("solver", {}).get("relative_residual")
                 for item in state["experiments"]]
    passed = (state.get("termination_reason") in {"BUDGET_EXHAUSTED", "GOAL_ACHIEVED", "PLATEAU"}
              and len(intents) >= 1 and all(value is not None and value < 1e-3 for value in residuals))
    return {"pass": passed, "termination": state.get("termination_reason"),
            "intents": intents, "real_fem_residuals": residuals}


def _online_gate(service: ResearchService) -> dict:
    research = service.create_research({"name": "Online Qwen gate", "mode": "CONTROLLED"})
    process = service.pi_runtime.start(research["id"])
    process.prompt("Call research_get_context exactly once, then answer QWEN_TOOL_GATE_OK.")
    deadline, events = time.time() + 60, []
    while time.time() < deadline:
        try:
            event = process.events.get(timeout=1)
            events.append(event)
            if event.get("type") == "agent_end": break
        except Exception:
            pass
    tool_seen = any(event.get("type") in {"tool_execution_start", "tool_call_start"}
                    and event.get("toolName") == "research_get_context" for event in events)
    messages = next((event.get("messages", []) for event in reversed(events)
                     if event.get("type") == "agent_end"), [])
    assistant = next((item for item in reversed(messages) if item.get("role") == "assistant"), {})
    error = assistant.get("errorMessage")
    return {"pass": bool(tool_seen and not error), "tool_seen": tool_seen,
            "model": assistant.get("model"), "provider": assistant.get("provider"),
            "error": str(error)[:300] if error else None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TopOptPilot release gates")
    parser.add_argument("--offline", action="store_true",
                        help="skip the Qwen network gate while retaining all desktop/MATLAB gates")
    args = parser.parse_args()
    report = run_audit(include_online=not args.offline)
    target = ROOT / "release_audit.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"offline_release_ready": report["offline_release_ready"],
                      "release_ready": report["release_ready"],
                      "online_qwen": report["online_qwen"]}, ensure_ascii=False, indent=2))
    return 0 if (report["offline_release_ready"] if args.offline else report["release_ready"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
