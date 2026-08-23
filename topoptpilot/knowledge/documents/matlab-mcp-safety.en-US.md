# MATLAB MCP controlled execution

Agents submit only Policy proposals. After safety, budget and approval gates, the deterministic Executor calls the single restricted `topopt_run_task` tool. JSON paths stay inside the research directory; arbitrary MATLAB, shell and external paths are unavailable.
