# ADR-0004：以受 Policy 约束的 topoptctl 作为无界面主入口

- 状态：已采纳
- 日期：2026-08-30
- 决策范围：TopOptPilot 2.0.3 后的无界面 MATLAB、Qwen 与 Research 自动化

## 背景

TopOptPilot 同时包含真实 MATLAB Engineering 运行、Pi/Qwen Agent、Research State 和 Policy 门禁。直接将桌面 API、任意 Shell 或任意 MATLAB 命令暴露给外部 Agent，会让模型绕过工况白名单、确认语义、参数约束、结果证据与人工审批。

用户需要即使不打开桌面软件，也能通过 Codex、Pi 或终端 Agent 使用项目；同时必须能证明运行结果是本次 MATLAB 任务产生的，而不是 UI 模拟值。

## 决策

采用仓库级 topoptctl，而不是把桌面应用或通用 Shell 暴露给 Agent。

1. topoptctl 仅连接自身创建的、127.0.0.1 上的认证 Sidecar。
2. CLI 任务采用 Pydantic 严格数据 Schema，拒绝未知字段、MATLAB 字符串、输出目录、任意工具名和任意路径。
3. Engineering 与 Research 分成不可混淆的命令命名空间。Engineering completed run 只能成为 Research 的基线证据；正式科学步骤必须继续通过 Policy。
4. 所有会改变计算或状态的命令均须 --confirm。普通 Agent 文本、JSON、Proposal 或运行 ID 不能代替确认。
5. Qwen Key 只经 Windows Credential Manager 或短生命周期环境变量取得。无界面写入只允许标准输入，禁止 --api-key 一类参数。
6. 工程导出只使用服务器给出的、带 SHA-256 的 artifact 清单，且导出目标必须是新建的 run 子目录。
7. 停止 daemon 前必须同时通过 Sidecar Session API 与 Windows 进程命令行验证身份，不能由陈旧状态文件任意杀 PID。

## 后果

优点：

- Codex、Pi、CI 和 PowerShell 都可复现相同的受控流程。
- 首轮 MATLAB、小任务、取消和导出均可以留下可验证证据。
- 误配置或模型幻觉只能导致结构化拒绝，而不能变成任意 MATLAB/系统操作。
- Policy 的审计源可识别 TOPoptctl，而不会伪装成 Pi。

代价：

- CLI 不是一个可任意扩展的工具箱；每个新能力要先定义数据契约、确认策略、审计边界和测试。
- 无界面使用仍需在本机准备 Python、MATLAB 和凭据。
- Engineering 基线和 Policy 科学实验之间的边界需要在报告中显式说明。

## CLI-Anything 决策

暂不把 CLI-Anything 作为核心运行时。当前受限 CLI 已覆盖验收工作流，额外生成一个泛化 Harness 会扩张攻击面并削弱可审计性。

只有当一个已经证明有价值的工作流无法由稳定 allowlist 表示时，才可以使用 CLI-Anything 辅助生成候选适配层。候选层必须：

1. 不接受任意 Shell、路径、MATLAB 或 API 工具名；
2. 复用 topoptctl 的确认、凭据、Sidecar 身份和导出哈希规则；
3. 为异常输入、取消、令牌泄露、路径遍历和状态误报补充回归测试；
4. 通过安全审查后才可接入，且不能取代核心 CLI。

## 验证依据

实施验证记录见 docs/validation/2026-08-30-topoptctl-headless-e2e.md。该记录明确区分完成的 20 x 10 二维工程基线与已取消的压力测试，不把低迭代灰度结果或 cancelled 运行称为完成设计。
