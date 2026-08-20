---
name: fidelity-budgeting
description: Allocates budget across F0 2D coarse, F1 2D fine, F2 Python 3D, and F3 MATLAB 3D. Use before any fidelity upgrade or high-fidelity recommendation.
allowed-tools: research_get_context research_get_budget policy_compile_intent experiment_preview
---

# Fidelity Budgeting

Promote only a feasible or near-feasible non-dominated candidate. Require reproducible F1 evidence
before F2. F3 requires remaining high-fidelity budget, successful F2 transfer evidence, and explicit
human approval. Prefer cached verified F3 replay when live MATLAB is unavailable.

