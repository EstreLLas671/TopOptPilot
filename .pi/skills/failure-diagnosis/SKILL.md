---
name: topopt-failure-diagnosis
description: Diagnoses HIGH_GRAY, DISCONNECTION, DIVERGENCE, OSCILLATION, VOLUME_VIOLATION, and POOR_COMPLIANCE from deterministic FEM evidence. Use after failed or partially successful experiments.
allowed-tools: research_get_context failure_get_evidence research_query_history experiment_compare policy_compile_intent
---

# Failure Diagnosis

Start from evaluator labels, not visual intuition. Retrieve failure evidence and relevant history.
Separate observations from possible causes. If two causes remain plausible, request
`TEST_COMPETING_EXPLANATIONS`; the DOE engine must vary one factor per branch. Never call a
correlation causal unless the comparison is controlled.

