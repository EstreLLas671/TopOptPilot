# MATLAB MCP 安全调用规范

Agent 只能提交 Policy 生成的 proposal。确定性 Executor 在预算、安全和审批通过后，通过唯一受控工具 `topopt_run_task` 调用 MATLAB。任务和结果 JSON 必须位于当前研究目录，禁止任意 MATLAB 代码、Shell 和目录外路径。

MCP 与 MATLAB 会话保持常驻以减少启动时间；所有原始日志、版本、入口哈希、任务哈希和失败证据进入 Artifact 血缘。
