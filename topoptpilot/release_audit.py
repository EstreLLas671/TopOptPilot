"""Executable V5 release gates. Run: python -m topoptpilot.release_audit"""

from __future__ import annotations

import json
import argparse
import tempfile
import time
from pathlib import Path

from topoptpilot.benchmarks import BenchmarkRunner
from topoptpilot.benchmarks.equivalence import run_equivalence_gate
from topoptpilot.cases import EvidenceCaseRunner
from topoptpilot.service import ResearchService
from topoptpilot.tools import ALLOWED_TOOLS
from mcp.matlab_mcp import MatlabMcpWorker
from solver.matlab3d_adapter import run_matlab3d_or_replay


ROOT = Path(__file__).resolve().parents[1]


def run_audit(include_online: bool = True) -> dict:
    report = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "version": "6.1.1", "gates": {}}
    report["gates"]["artifacts"] = _artifact_gate()
    report["gates"]["desktop_app"] = _desktop_gate()
    report["gates"]["strict_f3"] = _strict_f3_gate()
    report["gates"]["i18n_zh_default"] = _i18n_gate()
    report["gates"].update(_v6_source_gates())
    report["gates"].update(_matlab_mcp_gates())
    with tempfile.TemporaryDirectory(prefix="topoptpilot_release_") as directory:
        service = ResearchService(directory, max_workers=2, enable_agent_runtime=include_online)
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
            report["gates"]["cases"] = {"pass": _cases_gate_passes(report["cases"])}
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
            report["gates"]["pi_closed_loop"] = {
                "pass": report["online_qwen"].get("closed_loop") if include_online else None}
            report["gates"]["benchmark_pi_vs_baselines"] = {
                "pass": report["online_qwen"].get("pass") if include_online else None}
            if report["online_qwen"].get("metrics"):
                report["baselines"]["Pi"] = report["online_qwen"]["metrics"]
        finally:
            service.close()
    online_only = {"online_qwen", "pi_closed_loop", "benchmark_pi_vs_baselines"}
    required = [value["pass"] for key, value in report["gates"].items() if key not in online_only]
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
    release_dir = ROOT / "desktop/src-tauri/target/release"
    executable_candidates = (release_dir / "topoptpilot.exe",)
    installer_dir = release_dir / "bundle/nsis"
    installer_candidates = (installer_dir / "TopOptPilot_2.0.1_x64-setup.exe",)
    executable = next((path for path in executable_candidates if path.exists()), executable_candidates[0])
    installer = next((path for path in installer_candidates if path.exists()), installer_candidates[0])
    resources = release_dir / "resources"
    required_resources = (
        "bin/topoptpilot-backend.exe",
        "node/node.exe",
        "vendor/matlab-mcp-server/matlab-mcp-server-windows-x64.exe",
        "mcp/matlab_mcp/topopt-tools.json",
        "求解器模块/2D/TopOpt_integrated/TopOpt_integrated/topopt_main.m",
        "求解器模块/TopOpt-3D/TopOpt-3D/topopt3d_main.m",
    )
    missing_resources = [relative for relative in required_resources if not (resources / relative).is_file()]
    runtime_in_standard_package = (resources / "runtime").exists()
    passed = executable.is_file() and installer.is_file() and not missing_resources and not runtime_in_standard_package
    return {
        "pass": passed,
        "package_kind": "standard-local-matlab",
        "runtime_optional": True,
        "runtime_in_standard_package": runtime_in_standard_package,
        "missing_resources": missing_resources,
        "executable": str(executable),
        "installer": str(installer),
    }

def _cases_gate_passes(cases: dict) -> bool:
    """Require the staged evidence case to reach F3 through MATLAB MCP."""
    return (
        cases["A"]["metrics"]["best_feasible_objective"] is not None
        and cases["B"]["experiments"] >= 6
        and cases["C"]["fidelities"][-4:] == ["F0", "F1", "F2", "F3"]
        and any("matlab_mcp_3d" in value for value in cases["C"]["real_backends"])
    )

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


def _v6_source_gates() -> dict:
    store = (ROOT / "topoptpilot/memory/research_state.py").read_text(encoding="utf-8")
    service = (ROOT / "topoptpilot/service/research_service.py").read_text(encoding="utf-8")
    app = (ROOT / "desktop/src/App.tsx").read_text(encoding="utf-8")
    canvas = (ROOT / "desktop/src/ExperimentCanvas.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "desktop/src/styles.css").read_text(encoding="utf-8")
    api = (ROOT / "topoptpilot/api/fastapi_app.py").read_text(encoding="utf-8")
    credentials = (ROOT / "topoptpilot/security/credentials.py").read_text(encoding="utf-8")
    subagents = (ROOT / "topoptpilot/agent_runtime/subagents.py").read_text(encoding="utf-8")
    knowledge = (ROOT / "topoptpilot/knowledge/base.py").read_text(encoding="utf-8")
    fidelity = (ROOT / "topoptpilot/fidelity/manager.py").read_text(encoding="utf-8")
    report = (ROOT / "topoptpilot/reports/generator.py").read_text(encoding="utf-8")
    setup = (ROOT / "desktop/src/ResearchSetup.tsx").read_text(encoding="utf-8")
    return {
        "v5_visual_consistency": {"pass": "#101114" in styles and "#346bd8" in styles},
        "research_contract": {"pass": "contract_json" in store and '"immutable": True' in service},
        "agent_provenance": {"pass": all(value in store for value in
            ("decision_source", "intent_source", "policy_version", "evidence_ids_json"))},
        "evaluator_first": {"pass": service.find('EventKind.EVIDENCE.value') <
            service.find('EXPERIMENT_BATCH_COMPLETED')},
        "websocket_realtime": {"pass": "stream-ticket" in api and "_ws_tickets.pop" in api
            and "?ticket=" in (ROOT / "desktop/src/api.ts").read_text(encoding="utf-8")},
        "experiment_canvas": {"pass": "ExperimentCanvas" in app and all(
            value in canvas for value in ("SETUP", "HYPOTHESIS", "PLAN", "RUN", "ANALYZE",
                                          "COMPARE", "DECIDE", "REPORT", "TIMELINE"))},
        "guided_setup": {"pass": "previewGuide" in setup and "AI_SUGGESTED" in setup
            and "Confirm Research Contract" in setup},
        "offline_knowledge": {"pass": "knowledge_fts" in knowledge
            and len(list((ROOT / "topoptpilot/knowledge/documents").glob("*.md"))) >= 10},
        "isolated_subagents": {"pass": all(role in subagents for role in
            ("GUIDE", "HYPOTHESIS", "EXPERIMENT_PLANNER", "EXPERIMENT_EXECUTOR",
             "INDEPENDENT_REVIEWER", "REPORT_WRITER")) and "ROLE_TOOLS" in subagents},
        "fidelity_lane_mapping": {"pass": all(value in fidelity for value in (
            '"F0": "python"', '"F1": "python"', '"F2": "python3d"',
            '"F3": "matlab"'))},
        "fact_grounded_reports": {"pass": all(value in report for value in (
            "未计算", "evaluation", "artifact_lineage", "SHA256", "不得输出成功结论"))},
        "credential_not_in_sqlite": {"pass": "api_key" not in store.lower()
            and "/api/settings/agent-key" in api
            and "/api/settings/agent-credential" in api
            and "DASHSCOPE_API_KEY" in service
            and 'TARGET = "TopOptPilot/QwenOpenAICompatible"' in credentials
            and "CredWriteW" in credentials and "CredReadW" in credentials
            and "CredDeleteW" in credentials},
    }


def _matlab_mcp_gates() -> dict:
    output = {}
    with tempfile.TemporaryDirectory(prefix="topoptpilot_matlab_gate_") as directory:
        worker = MatlabMcpWorker(directory, ROOT)
        try:
            common = {"load_case": "cantilever", "projection": "heaviside_projection",
                      "params": {"volfrac": .4, "penal": 3, "rmin": 1.5, "max_iter": 2}}
            for dimension, mesh, grid in ((2, "coarse", None), (3, "coarse3d", [4, 2, 2])):
                task = {**common, "task_id": f"audit-{dimension}d", "mesh_level": mesh,
                        "fidelity": "F0" if dimension == 2 else "F2",
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
            try:
                output["matlab_equivalence"] = run_equivalence_gate(worker, dimension=2)
            except Exception as exc:
                output["matlab_equivalence"] = {"pass": False, "error": str(exc)[:500]}
            try:
                worker.warmup()
                warmup = worker.health().get("warmup") or {}
                output["matlab_warmup"] = {"pass": True, **warmup}
            except Exception as exc:
                output["matlab_warmup"] = {"pass": False, "error": str(exc)[:500]}
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
    try:
        campaign = BenchmarkRunner().run_pi_campaign(service, budget=3, timeout=240)
    except Exception as exc:
        return {"pass": False, "closed_loop": False, "error": str(exc)[:300]}
    research = service.get_research(campaign["research_id"])
    events = research["events"]
    evaluator_positions = [index for index, item in enumerate(events)
                           if item.get("source") == "EVALUATOR"]
    later_pi_compile = any(index > min(evaluator_positions, default=10**9)
                           and item.get("source") == "PI_AGENT"
                           and item.get("title") == "policy_compile_intent"
                           for index, item in enumerate(events))
    pi_experiments = [item for item in research["experiments"]
                      if item.get("decision_source") == "PI_AGENT"]
    fallback = any(item.get("source") == "RULE_FALLBACK" for item in events)
    session = service.store.get_agent_session(research["id"]) or {}
    closed_loop = bool(len(pi_experiments) >= 2 and evaluator_positions and later_pi_compile
                       and not fallback)
    return {"pass": closed_loop, "closed_loop": closed_loop,
            "tool_seen": any(item.get("type") == "AGENT_TOOL_CALL" for item in events),
            "model": service.pi_runtime.model if service.pi_runtime else None,
            "provider": "dashscope", "metrics": campaign.get("metrics"),
            "pi_experiments": [item["id"] for item in pi_experiments],
            "fallback": fallback, "error": str(session.get("last_error") or "")[:300] or None}


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
