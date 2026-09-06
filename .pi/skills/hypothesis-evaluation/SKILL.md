---
name: hypothesis-evaluation
description: Evaluates a user-provided scientific hypothesis against experiment evidence. Use only when the research includes an explicit hypothesis or a hypothesis revision is proposed.
allowed-tools: research_get_context research_query_history experiment_compare
---

# Hypothesis Evaluation

Never rewrite the user's hypothesis silently. Assign one evidence state: `SUPPORTING`, `NEUTRAL`,
`CONTRADICTING`, `UNDER_STRESS`, or `REVISED`. A revision must be shown as a proposal and requires
human approval. Cite experiment IDs for every evidence statement.

