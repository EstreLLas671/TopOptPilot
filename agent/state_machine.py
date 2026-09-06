"""
科研闭环状态机。

定义了 AI Scientist 从任务接收到结论输出的完整状态转换。
每个状态对应一个 Agent 角色的决策步骤。
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class ResearchState(Enum):
    """科研闭环的离散状态"""
    INIT = "init"                           # 初始状态，等待输入
    INPUT_VALIDATION = "input_validation"   # 验证科研任务包完整性
    LITERATURE_MINING = "literature_mining" # 证据Agent：文献挖掘与方法提取
    HYPOTHESIS_GENERATION = "hypothesis_generation"  # 假设Agent：生成候选假设
    HYPOTHESIS_REVIEW = "hypothesis_review"          # 审稿Agent：评审候选假设
    EXPERIMENT_DESIGN = "experiment_design"          # 实验Agent：设计实验矩阵
    EXPERIMENT_EXECUTION = "experiment_execution"    # 实验执行：调用MATLAB/CUDA
    RESULT_AUDIT = "result_audit"           # 审计Agent：分析实验结果
    CONCLUSION = "conclusion"               # 结论输出
    FAILED = "failed"                       # 失败终止


class ActionType(Enum):
    """状态间转换的动作"""
    CONTINUE = "continue"       # 继续下一状态
    REITERATE = "reiterate"     # 回到上一状态进行修正
    STOP = "stop"               # 满足终止条件，输出结论


@dataclass
class Transition:
    """状态转换记录"""
    from_state: ResearchState
    to_state: ResearchState
    action: ActionType
    reason: str
    evidence: Optional[dict] = None


@dataclass
class ResearchCycleState:
    """
    科研循环的完整状态，包含所有跨轮持久化数据。
    每次迭代产生一个新的版本，用于审计追踪。
    """
    # 核心状态
    current_state: ResearchState = ResearchState.INIT
    iteration_count: int = 0
    max_iterations: int = 5

    # 输入
    research_goal: Optional[dict] = None
    task_package: Optional[dict] = None

    # 各阶段产物
    validation_result: Optional[dict] = None
    evidence_table: Optional[list] = None
    knowledge_gaps: Optional[list] = None
    hypotheses: Optional[list] = None
    review_ranks: Optional[list] = None
    experiment_matrix: Optional[list] = None
    experiment_results: Optional[list] = None
    audit_verdicts: Optional[list] = None

    # 结论
    conclusion: Optional[dict] = None

    # 历史轨迹
    transitions: list[Transition] = field(default_factory=list)
    termination_reason: Optional[str] = None

    # 计算预算跟踪
    runs_remaining: int = 30
    budget_exhausted: bool = False

    # 实验迭代决策
    last_iteration_gained_info: bool = True
    consecutive_no_gain_count: int = 0
    max_no_gain_rounds: int = 2


class StateMachine:
    """状态机：驱动科研循环的离散状态转换"""

    def __init__(self, max_iterations: int = 5):
        self.state = ResearchCycleState()
        self.state.max_iterations = max_iterations

    def transition_to(self, to_state: ResearchState, action: ActionType, reason: str,
                      evidence: Optional[dict] = None) -> bool:
        """执行状态转换并记录"""
        from_state = self.state.current_state

        if not self._is_valid_transition(from_state, to_state):
            return False

        transition = Transition(
            from_state=from_state,
            to_state=to_state,
            action=action,
            reason=reason,
            evidence=evidence
        )
        self.state.transitions.append(transition)
        self.state.current_state = to_state

        if action == ActionType.STOP:
            self.state.termination_reason = reason

        if to_state == ResearchState.LITERATURE_MINING and from_state != ResearchState.INIT:
            self.state.iteration_count += 1

        return True

    def _is_valid_transition(self, current: ResearchState, next_: ResearchState) -> bool:
        """验证状态转换合法性"""
        valid_transitions = {
            ResearchState.INIT: [ResearchState.INPUT_VALIDATION],
            ResearchState.INPUT_VALIDATION: [
                ResearchState.LITERATURE_MINING, ResearchState.FAILED],
            ResearchState.LITERATURE_MINING: [
                ResearchState.HYPOTHESIS_GENERATION, ResearchState.FAILED],
            ResearchState.HYPOTHESIS_GENERATION: [
                ResearchState.HYPOTHESIS_REVIEW, ResearchState.LITERATURE_MINING],
            ResearchState.HYPOTHESIS_REVIEW: [
                ResearchState.EXPERIMENT_DESIGN, ResearchState.HYPOTHESIS_GENERATION],
            ResearchState.EXPERIMENT_DESIGN: [
                ResearchState.EXPERIMENT_EXECUTION, ResearchState.HYPOTHESIS_GENERATION],
            ResearchState.EXPERIMENT_EXECUTION: [
                ResearchState.RESULT_AUDIT, ResearchState.FAILED],
            ResearchState.RESULT_AUDIT: [
                ResearchState.CONCLUSION, ResearchState.EXPERIMENT_DESIGN,
                ResearchState.LITERATURE_MINING, ResearchState.HYPOTHESIS_GENERATION],
            ResearchState.CONCLUSION: [],
            ResearchState.FAILED: [],
        }
        return next_ in valid_transitions.get(current, [])

    def should_stop(self) -> bool:
        """检查终止条件"""
        state = self.state

        # 1) 达到成功门槛
        if state.conclusion and state.conclusion.get("is_final"):
            return True

        # 2) 连续无信息增益
        if state.consecutive_no_gain_count >= state.max_no_gain_rounds:
            state.termination_reason = f"连续{state.max_no_gain_rounds}轮无信息增益"
            return True

        # 3) 预算耗尽
        if state.runs_remaining <= 0:
            state.termination_reason = "计算预算耗尽"
            return True

        # 4) 最大迭代次数
        if state.iteration_count >= state.max_iterations:
            state.termination_reason = f"达到最大迭代次数({state.max_iterations})"
            return True

        return False