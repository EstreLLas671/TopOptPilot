# MATLAB MCP controlled execution

Agents submit only Policy proposals. After safety validation and consumption of the one-time Step4 human authorization, the deterministic Executor calls the single restricted `topopt_run_task` tool. JSON paths stay inside the research directory; arbitrary MATLAB, shell and external paths are unavailable.
