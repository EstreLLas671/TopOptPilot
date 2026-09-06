"""AI Scientist 六角色模块"""

from .research_lead import ResearchLead, ResearchGoal, TaskDecomposition
from .evidence_agent import EvidenceAgent, EvidenceTable, MethodCard, KnowledgeGap
from .hypothesis_agent import HypothesisAgent, HypothesisSet, CandidateHypothesis
from .review_agent import ReviewAgent, ReviewResult, ReviewScore, CounterExample
from .experiment_agent import ExperimentAgent, ExperimentMatrix, ExperimentTask
from .audit_agent import AuditAgent, AuditVerdict, VerdictLevel, ExperimentResult, ResultAnalyzer

__all__ = [
    'ResearchLead', 'ResearchGoal', 'TaskDecomposition',
    'EvidenceAgent', 'EvidenceTable', 'MethodCard', 'KnowledgeGap',
    'HypothesisAgent', 'HypothesisSet', 'CandidateHypothesis',
    'ReviewAgent', 'ReviewResult', 'ReviewScore', 'CounterExample',
    'ExperimentAgent', 'ExperimentMatrix', 'ExperimentTask',
    'AuditAgent', 'AuditVerdict', 'VerdictLevel', 'ExperimentResult', 'ResultAnalyzer',
]