---
name: topopt-experiment-planning
description: Plans baseline, exploration, refinement, and controlled topology-optimization experiments. Use at the beginning of every research round and whenever a next experiment must be selected.
allowed-tools: research_get_context research_get_budget policy_compile_intent experiment_preview experiment_submit
---

# Topology Optimization Experiment Planning

1. Call `research_get_context`, then `research_get_budget`.
2. Identify exactly one current scientific question.
3. Prefer F0 before F1, and do not upgrade fidelity without stable 2D evidence.
4. Avoid any configuration already present in recent experiments.
5. Express the next action as an intent; never choose raw parameters yourself.
6. Call `policy_compile_intent`, preview every returned proposal, then submit only proposals marked safe.
7. End the turn immediately after submission. The worker runs FEM asynchronously.

Valid intents include `ESTABLISH_BASELINE`, `EXPLORE_PARAMETER`, `REDUCE_GRAYNESS`,
`RESTORE_CONNECTIVITY`, `TEST_COMPETING_EXPLANATIONS`, and `UPGRADE_FIDELITY`.

