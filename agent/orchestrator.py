"""
TopOptPilot 主编排器 (Orchestrator) — LLM 驱动版本

运行 AI Scientist 科研闭环：
  输入验证 → 文献挖掘(LLM) → 假设生成(LLM) → 审稿(LLM)
  → 实验设计(LLM) → 实验执行 → 审计(LLM) → 迭代/终止

Phase 0 改进：
  - LLM Client 替代硬编码逻辑
  - 结构化输出约束 (JSON Schema)
  - 指数退避重试 (3次)
  - NaN/Inf 运行时检测
  - 实验队列异步化
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from agent.state_machine import (
    ResearchState, ActionType, StateMachine
)
from agent.roles.research_lead import ResearchLead, ResearchGoal
from agent.roles.evidence_agent import EvidenceAgent
from agent.roles.hypothesis_agent import HypothesisAgent, HypothesisSet, CandidateHypothesis
from agent.roles.review_agent import ReviewAgent, ReviewResult, ReviewScore, CounterExample
from agent.roles.experiment_agent import ExperimentAgent, ExperimentTask, ExperimentMatrix
from agent.roles.audit_agent import AuditAgent, AuditVerdict, VerdictLevel
from agent.llm.client import PiAgentClient
from agent.llm.message_builder import MessageBuilder
from agent.llm.response_parser import ResponseParser
from experiments.experiment_queue import ExperimentQueue
from experiments.result_manager import ResultManager, NaNChecker


class TopOptPilotOrchestrator:
    """AI Scientist 主编排器（LLM 驱动版本）"""

    def __init__(self, api_key: str = None, base_url: str = None,
                 model: str = None, config_path: Optional[str] = None):
        self.sm = StateMachine(max_iterations=5)
        self.config = self._load_config(config_path)

        self.llm_client = PiAgentClient(
            api_key=api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("LLM_API_KEY", ""),
            base_url=base_url or os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            model=model or os.getenv("QWEN_MODEL", "qwen3.7-plus"),
        )
        self.message_builder = MessageBuilder()
        self.parser = ResponseParser()

        self.research_lead = ResearchLead()
        self.evidence_agent = EvidenceAgent()
        self.hypothesis_agent = HypothesisAgent()
        self.review_agent = ReviewAgent()
        self.experiment_agent = ExperimentAgent()
        self.audit_agent = AuditAgent()

        self.experiment_queue = ExperimentQueue()
        self.result_manager = ResultManager()
        self.results_store = []

        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("TopOptPilot")

    def _load_config(self, config_path: Optional[str]) -> dict:
        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                return json.load(f)
        return {
            "max_iterations": 5,
            "max_no_gain_rounds": 2,
            "default_volume_fraction": 0.40
        }

    def run(self, task_package: dict) -> dict:
        self.logger.info(f"=== TopOptPilot 启动 === 任务: {task_package.get('task_id', 'unknown')}")

        self.sm.state.task_package = task_package
        self.sm.state.research_goal = ResearchGoal(
            task_id=task_package.get("task_id", ""),
            description=task_package.get("research_goal", ""),
            geometry_path=task_package.get("geometry", ""),
            material=task_package.get("material"),
            load_cases=task_package.get("load_cases", []),
            volume_fraction=task_package.get("volume_fraction", 0.40),
            requirements=task_package.get("requirements", {}),
            compute_budget=task_package.get("compute_budget", {})
        )
        self.sm.state.runs_remaining = task_package.get("compute_budget", {}).get("max_runs", 30)

        self._phase_input_validation(task_package)
        if self.sm.state.current_state == ResearchState.FAILED:
            return self._generate_report()

        self._phase_literature_mining_llm(task_package)

        while not self.sm.should_stop():
            self._phase_hypothesis_generation_llm()
            self._phase_hypothesis_review_llm()
            self._phase_experiment_design_llm(task_package)
            self._phase_experiment_execution_async()
            self._phase_result_audit_llm()
            self.sm.state.iteration_count += 1
            self.logger.info(f"迭代 {self.sm.state.iteration_count} 完成")
            if self._check_nan_in_results():
                self.logger.warning("检测到 NaN/Inf，进入回滚流程")
                self.sm.state.consecutive_no_gain_count += 1

        self._phase_conclusion()
        self.logger.info("=== TopOptPilot 完成 ===")
        return self._generate_report()

    def _phase_input_validation(self, task_package: dict):
        self.logger.info("Phase 1: 输入验证")
        validation = self.research_lead.validate_task_package(task_package)
        self.sm.state.validation_result = validation
        if not validation["valid"]:
            self.sm.transition_to(
                ResearchState.FAILED, ActionType.STOP,
                f"任务包不完整: {validation['missing_fields']}"
            )
            return
        self.sm.transition_to(
            ResearchState.LITERATURE_MINING, ActionType.CONTINUE,
            "任务包验证通过"
        )

    def _phase_literature_mining_llm(self, task_package: dict):
        """Phase 2: 文献挖掘 — LLM 驱动"""
        self.logger.info("Phase 2: 文献挖掘 (LLM)")
        messages = self.message_builder.build("evidence", {
            "research_goal": task_package.get("research_goal", ""),
            "paper_db_path": "./knowledge/storage/method_cards/",
            "constraints": task_package.get("requirements", {}),
        })
        llm_resp = self.llm_client.chat(
            messages, response_format={"type": "json_object"},
            temperature=0.2
        )
        if llm_resp["success"]:
            parsed = self.parser.parse_evidence(llm_resp["content"])
            self.sm.state.evidence_table = parsed.get("methods", [])
            self.sm.state.knowledge_gaps = parsed.get("knowledge_gaps", [])
            self.logger.info(f"LLM 文献挖掘: {len(parsed.get('methods', []))} 个方法, "
                           f"{len(parsed.get('knowledge_gaps', []))} 个缺口")
        else:
            self.logger.warning(f"LLM 不可用，降级到规则检索: {llm_resp['error']}")
            evidence = self.evidence_agent.search_methods(
                task_package.get("research_goal", ""),
                task_package.get("requirements")
            )
            self.sm.state.evidence_table = evidence.methods
            self.sm.state.knowledge_gaps = evidence.gaps
        self.sm.transition_to(
            ResearchState.HYPOTHESIS_GENERATION, ActionType.CONTINUE,
            "文献挖掘完成"
        )

    def _phase_hypothesis_generation_llm(self):
        """Phase 3: 假设生成 — LLM 驱动"""
        self.logger.info("Phase 3: 假设生成 (LLM)")

        gaps = self.sm.state.knowledge_gaps or []
        # Safely extract descriptions regardless of whether items are dicts or objects
        if gaps and isinstance(gaps[0], dict):
            gap_descriptions = [g.get("description", str(g)) for g in gaps]
        else:
            gap_descriptions = [getattr(g, "description", str(g)) for g in gaps]

        context = {
            "knowledge_gaps": json.dumps(gap_descriptions, ensure_ascii=False),
            "research_goal": self.sm.state.research_goal.description if self.sm.state.research_goal else "",
            "history_count": len(self.results_store),
        }
        messages = self.message_builder.build("hypothesis", context)
        llm_resp = self.llm_client.chat(
            messages, response_format={"type": "json_object"},
            temperature=0.3
        )
        if llm_resp["success"]:
            hypotheses_data = self.parser.parse_hypotheses(llm_resp["content"])
            hs = HypothesisSet(research_goal=context["research_goal"])
            for i, hdata in enumerate(hypotheses_data[:5]):
                hs.add(CandidateHypothesis(
                    id=hdata.get("id", f"H{i+1}"),
                    title=hdata.get("title", ""),
                    statement=hdata.get("statement", ""),
                    reasoning_chain=hdata.get("reasoning_chain", []),
                    success_conditions=hdata.get("success_conditions", {}),
                    failure_conditions=hdata.get("failure_conditions", {}),
                    baseline=hdata.get("baseline", ""),
                    metrics=hdata.get("metrics", []),
                    required_plugins=hdata.get("required_plugins", []),
                    compute_budget_estimate=hdata.get("compute_budget_estimate", 5),
                    derivation=json.dumps(hdata, ensure_ascii=False)
                ))
            self.sm.state.hypotheses = hs
            self.logger.info(f"LLM 生成 {len(hs)} 个假设")
        else:
            self.logger.warning(f"LLM 不可用，降级到预设假设: {llm_resp['error']}")
            hs = self.hypothesis_agent.generate_hypotheses(
                knowledge_gaps=gap_descriptions,
                research_goal={"description": context["research_goal"]},
                historical_results=self.results_store
            )
            self.sm.state.hypotheses = hs
        self.sm.transition_to(
            ResearchState.HYPOTHESIS_REVIEW, ActionType.CONTINUE,
            f"生成 {len(self.sm.state.hypotheses)} 个候选假设" if self.sm.state.hypotheses else "生成 0 个候选假设"
        )

    def _phase_hypothesis_review_llm(self):
        """Phase 4: 审稿 — LLM 驱动"""
        self.logger.info("Phase 4: 假设审稿 (LLM)")
        if not self.sm.state.hypotheses or len(self.sm.state.hypotheses) == 0:
            self.sm.transition_to(
                ResearchState.HYPOTHESIS_GENERATION, ActionType.REITERATE,
                "无假设可审，回退生成"
            )
            return

        hypotheses_summary = []
        for h in self.sm.state.hypotheses.hypotheses:
            hypotheses_summary.append({
                "id": h.id, "title": h.title,
                "statement": h.statement[:200],
                "metrics": h.metrics,
                "budget": h.compute_budget_estimate
            })
        messages = self.message_builder.build("review", {
            "hypotheses": json.dumps(hypotheses_summary, ensure_ascii=False)
        })
        llm_resp = self.llm_client.chat(
            messages, response_format={"type": "json_object"},
            temperature=0.2
        )
        if llm_resp["success"]:
            reviews_data = self.parser.parse_reviews(llm_resp["content"])
            reviews = []
            for i, rdata in enumerate(reviews_data):
                hid = rdata.get("hypothesis_id", f"H{i+1}")
                scores_raw = rdata.get("scores", {})
                reviews.append(ReviewResult(
                    hypothesis_id=hid,
                    scores=ReviewScore(
                        novelty=scores_raw.get("novelty", 5),
                        physical_consistency=scores_raw.get("physical_consistency", 5),
                        falsifiability=scores_raw.get("falsifiability", 5),
                        compute_cost=scores_raw.get("compute_cost", 5),
                    ),
                    counter_examples=[
                        CounterExample(
                            hypothesis_id=hid,
                            scenario=ce.get("scenario", ""),
                            physical_reason=ce.get("physical_reason", ""),
                            severity=ce.get("severity", "medium"),
                        ) for ce in rdata.get("counter_examples", [])
                    ],
                    summary=rdata.get("summary", ""),
                    rank=rdata.get("rank", i + 1)
                ))
            reviews.sort(key=lambda r: r.rank)
            self.sm.state.review_ranks = reviews
            self.logger.info(f"LLM 审稿完成: {len(reviews)} 条评审")
        else:
            self.logger.warning(f"LLM 不可用，降级到规则审稿: {llm_resp['error']}")
            reviews = self.review_agent.review_hypotheses(self.sm.state.hypotheses)
            self.sm.state.review_ranks = reviews
        self.sm.transition_to(
            ResearchState.EXPERIMENT_DESIGN, ActionType.CONTINUE,
            "审稿完成"
        )

    def _phase_experiment_design_llm(self, task_package: dict):
        """Phase 5: 实验设计 — LLM + 兼容性规则混合"""
        self.logger.info("Phase 5: 实验设计 (LLM)")
        if not self.sm.state.hypotheses or not self.sm.state.review_ranks:
            self.sm.transition_to(
                ResearchState.HYPOTHESIS_GENERATION, ActionType.REITERATE,
                "缺少假设或评审结果"
            )
            return

        top_review = self.sm.state.review_ranks[0] if self.sm.state.review_ranks else None
        context = {
            "best_hypothesis_id": top_review.hypothesis_id if top_review else "H1",
            "load_cases": task_package.get("load_cases", ["vertical"]),
            "mesh_levels": ["coarse", "medium", "fine"],
        }
        messages = self.message_builder.build("experiment", context)
        llm_resp = self.llm_client.chat(
            messages, response_format={"type": "json_object"},
            temperature=0.2
        )
        if llm_resp["success"]:
            tasks_data = self.parser.parse_experiment_tasks(llm_resp["content"])
            matrix = ExperimentMatrix(description=f"LLM 实验方案 ({len(tasks_data)} tasks)")
            for td in tasks_data:
                task = ExperimentTask(
                    task_id=td.get("task_id", f"exp_llm_{len(matrix.tasks)+1:03d}"),
                    experiment_group=td.get("experiment_group", "Ours"),
                    hypothesis_id=td.get("hypothesis_id", "H1"),
                    solver=td.get("solver", "cuda_mex"),
                    optimizer=td.get("optimizer", "OC"),
                    filter=td.get("filter", "PDE_filter"),
                    projection=td.get("projection", "heaviside_projection"),
                    controller=td.get("controller", "joint_feedback_controller"),
                    evaluator=td.get("evaluator", "standard_evaluator"),
                    load_case=td.get("load_case", "vertical"),
                    mesh_level=td.get("mesh_level", "medium"),
                    params=td.get("params", {}),
                )
                validation = self.experiment_agent.validate_plugin_combination(task)
                if validation["valid"]:
                    matrix.add_task(task)
                else:
                    self.logger.warning(f"插件组合非法: {task.task_id} - {validation}")
            self.sm.state.experiment_matrix = matrix
        else:
            self.logger.warning(f"LLM 不可用，降级到规则实验设计: {llm_resp['error']}")
            matrix = self.experiment_agent.design_experiment_matrix(
                self.sm.state.hypotheses, self.sm.state.review_ranks, task_package
            )
            self.sm.state.experiment_matrix = matrix

        self.sm.state.runs_remaining -= (self.sm.state.experiment_matrix.total_runs()
                                         if self.sm.state.experiment_matrix else 0)
        self.sm.transition_to(
            ResearchState.EXPERIMENT_EXECUTION, ActionType.CONTINUE,
            f"实验设计完成: {self.sm.state.experiment_matrix.total_runs() if self.sm.state.experiment_matrix else 0}组"
        )

    def _phase_experiment_execution_async(self):
        """Phase 6: 实验执行 — 异步队列"""
        self.logger.info("Phase 6: 实验执行 (异步队列)")
        if not self.sm.state.experiment_matrix:
            self.sm.transition_to(
                ResearchState.EXPERIMENT_DESIGN, ActionType.REITERATE,
                "无实验矩阵可执行"
            )
            return
        for task in self.sm.state.experiment_matrix.tasks:
            run_id = self.experiment_queue.submit(task)
            self.logger.info(f"  提交实验: {task.task_id} -> {run_id}")
        max_wait = 30
        poll_interval = 2
        waited = 0
        while waited < max_wait:
            status = self.experiment_queue.get_status_summary()
            completed = status["by_status"].get("completed", 0) + status["by_status"].get("failed", 0)
            if completed == status["total"]:
                break
            time.sleep(poll_interval)
            waited += poll_interval
        self.results_store = self.experiment_queue.get_all_results()
        self.logger.info(f"实验执行完成: {len(self.results_store)} 个结果")
        self.sm.transition_to(
            ResearchState.RESULT_AUDIT, ActionType.CONTINUE,
            f"实验执行完成: {len(self.results_store)} 组"
        )

    def _phase_result_audit_llm(self):
        """Phase 7: 结果审计 — LLM 驱动"""
        self.logger.info("Phase 7: 结果审计 (LLM)")
        if not self.sm.state.hypotheses or len(self.sm.state.hypotheses) == 0:
            self.sm.transition_to(
                ResearchState.HYPOTHESIS_GENERATION, ActionType.REITERATE,
                "无假设可审计"
            )
            return

        nan_issues = self._check_nan_in_results()
        if nan_issues:
            self.logger.warning(f"NaN 检测发现问题: {nan_issues}")
            self.sm.state.audit_verdicts = [
                AuditVerdict(
                    hypothesis_id=h.id,
                    level=VerdictLevel.INSUFFICIENT_EVIDENCE,
                    evidence_summary=f"实验结果含 NaN/Inf: {nan_issues}",
                    next_action="reiterate",
                    confidence=0.0
                )
                for h in self.sm.state.hypotheses.hypotheses
            ]
            self.sm.state.consecutive_no_gain_count += 1
            self._decide_next_iteration()
            return

        results_summary = [{
            "run_id": r.run_id,
            "hypothesis_id": r.hypothesis_id,
            "status": r.status,
            "compliance": r.objective.get("compliance", 0),
            "gray_ratio": r.quality.get("gray_ratio", 1.0),
            "connected": r.quality.get("connected_components", 0) == 1,
        } for r in self.results_store[-10:]]

        messages = self.message_builder.build("audit", {
            "results_count": len(results_summary),
            "results_summary": json.dumps(results_summary, ensure_ascii=False),
        })
        llm_resp = self.llm_client.chat(
            messages, response_format={"type": "json_object"},
            temperature=0.2
        )
        if llm_resp["success"]:
            verdicts_data = self.parser.parse_verdicts(llm_resp["content"])
            verdicts = []
            for vd in verdicts_data:
                try:
                    level = VerdictLevel(vd.get("level", "insufficient_evidence"))
                except ValueError:
                    level = VerdictLevel.INSUFFICIENT_EVIDENCE
                verdicts.append(AuditVerdict(
                    hypothesis_id=vd.get("hypothesis_id", "unknown"),
                    level=level,
                    evidence_summary=vd.get("evidence_summary", ""),
                    diagnostics=vd.get("diagnostics", []),
                    applicability_boundary=vd.get("applicability_boundary", ""),
                    next_action=vd.get("next_action", "continue"),
                    confidence=vd.get("confidence", 0.5),
                ))
            self.sm.state.audit_verdicts = verdicts
        else:
            self.logger.warning(f"LLM 不可用，降级到规则审计: {llm_resp['error']}")
            verdicts = self.audit_agent.audit_results(
                self.results_store, self.sm.state.hypotheses
            )
            self.sm.state.audit_verdicts = verdicts

        has_gain = any(
            v.level.name in ["SUPPORTED", "PARTIALLY_SUPPORTED", "NOT_SUPPORTED"]
            for v in (self.sm.state.audit_verdicts or [])
        )
        if has_gain:
            self.sm.state.consecutive_no_gain_count = 0
        else:
            self.sm.state.consecutive_no_gain_count += 1
        self._decide_next_iteration()

    def _check_nan_in_results(self) -> list:
        issues = []
        for r in self.results_store:
            result_dict = {
                "compliance": r.objective.get("compliance"),
                "gray_ratio": r.quality.get("gray_ratio"),
                "residual": r.solver.get("relative_residual"),
            }
            nan_issues = NaNChecker.check_result(result_dict)
            if nan_issues:
                issues.append({"run_id": r.run_id, "issues": nan_issues})
        return issues

    def _decide_next_iteration(self):
        if self.sm.should_stop():
            self.sm.transition_to(
                ResearchState.CONCLUSION, ActionType.STOP,
                f"终止条件满足: {self.sm.state.termination_reason}"
            )
        else:
            self.sm.transition_to(
                ResearchState.LITERATURE_MINING, ActionType.CONTINUE,
                "进入下一轮迭代"
            )

    def _phase_conclusion(self):
        self.logger.info("Phase 8: 结论")
        self.sm.state.current_state = ResearchState.CONCLUSION

    def _generate_report(self) -> dict:
        hypotheses_list = []
        if self.sm.state.hypotheses:
            hypotheses_list = [
                {"id": h.id, "title": h.title, "status": h.status}
                for h in self.sm.state.hypotheses.hypotheses
            ]
        verdicts_list = []
        if self.sm.state.audit_verdicts:
            verdicts_list = [
                {
                    "hypothesis_id": v.hypothesis_id,
                    "level": v.level.value,
                    "confidence": v.confidence,
                    "next_action": v.next_action,
                    "diagnostics": v.diagnostics,
                }
                for v in self.sm.state.audit_verdicts
            ]
        return {
            "task_id": self.sm.state.task_package.get("task_id", "") if self.sm.state.task_package else "",
            "status": "completed" if self.sm.state.current_state == ResearchState.CONCLUSION else "partial",
            "termination_reason": self.sm.state.termination_reason,
            "total_iterations": self.sm.state.iteration_count,
            "total_experiments": len(self.results_store),
            "hypotheses": hypotheses_list,
            "verdicts": verdicts_list,
            "llm_enabled": self.llm_client.max_retries > 0,
            "conclusion": {
                "type": self.sm.state.termination_reason or "budget_exhausted",
                "applicability_boundary": verdicts_list[0].get("applicability_boundary", "")
                if verdicts_list else "",
                "cross_validation_passed": any(
                    v.get("level") == "supported" for v in verdicts_list
                ),
            }
        }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="TopOptPilot AI Scientist (LLM)")
    parser.add_argument("--task", type=str, default="demo/sample_inputs/bracket_task.json",
                        help="科研任务包 JSON 路径")
    parser.add_argument("--config", type=str, default=None,
                        help="系统配置 JSON 路径")
    parser.add_argument("--api-key", type=str, default=None,
                        help="LLM API Key (默认从 LLM_API_KEY 环境变量读取)")
    parser.add_argument("--base-url", type=str, default=None,
                        help="LLM API Base URL")
    parser.add_argument("--model", type=str, default=None,
                        help="LLM 模型名")
    parser.add_argument("--iterations", type=int, default=2,
                        help="最大迭代轮次")
    args = parser.parse_args()

    with open(args.task, encoding="utf-8") as f:
        task_package = json.load(f)

    api_key = args.api_key or os.getenv("LLM_API_KEY")
    if not api_key:
        print("错误: 未提供 API Key。使用 --api-key 参数或设置 LLM_API_KEY 环境变量。")
        sys.exit(1)

    orch = TopOptPilotOrchestrator(
        api_key=api_key,
        base_url=args.base_url,
        model=args.model,
        config_path=args.config,
    )
    orch.sm.state.max_iterations = args.iterations
    report = orch.run(task_package)

    print("\n" + "=" * 60)
    print("  TopOptPilot 研究结论报告")
    print("=" * 60)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("=" * 60)

    print("\n决策摘要:")
    for v in report.get("verdicts", []):
        icon = {"supported": "✅", "partially_supported": "🟡",
                "not_supported": "❌", "insufficient_evidence": "⚠️"}
        print(f"  {icon.get(v['level'], '❓')} {v['hypothesis_id']}: "
              f"{v['level']} (置信度: {v['confidence']:.2f})")
        if v.get("diagnostics"):
            for d in v["diagnostics"]:
                print(f"    - {d}")


if __name__ == "__main__":
    main()
