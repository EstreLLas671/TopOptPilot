# TopOptPilot 2.0.1 发布说明

发布日期：2026-08-29

TopOptPilot 2.0.1 是基于 2.0.0 的完整桌面更新，集中修复工作区高度、聊天输入框、暗色主题、真实 MATLAB 逐轮可视化和科研状态交互，并补齐安装版 sidecar 的 WebSocket 事件流支持。

## 主要更新

### 工程开发与实时 MATLAB 可视化

- MATLAB 仍是默认正式求解后端，Python FEM 保持可选。
- 优化启动后自动进入“迭代可视化 → MATLAB 原图”。
- 每轮真实 MATLAB PNG、密度、应力、柔度、体积分数和灰度率随快照事件更新。
- MATLAB 大图位于主画布，真实进度条和迭代指标位于图像下方。
- 相邻快照缓存与预取减少拖动迭代滑块时的等待；加载新帧时保留上一帧。
- 3D 密度和应力在切换迭代时保持旋转、缩放和平移视角。
- 运行期间“开始优化”切换为“停止优化”，取消后保留已生成的证据、日志和制品。

### 工作区与聊天布局

- 修复标题栏下方工作区额外占用 100% 高度导致内容越过窗口的问题。
- 底栏收起后工程中栏完整使用剩余高度，不再固定预留空白助手行。
- 工程聊天和科研聊天 Composer 始终位于可视区域底部；消息列表独立滚动。
- “过程 / 审计”标签不重复显示科研 Composer。
- 工程与科研模式切换后，未发送文本、附件草稿和工程运行状态继续保留。
- 用户与 Agent 消息气泡限制在聊天区域的 75% 以内，长文本、代码和哈希在气泡内部换行或滚动。
- 1920×1080、1440×900、1280×800 和 920×640 的明暗主题布局均完成实窗验收。

### AI 对话、附件与建议填入

- 文本、图片、PDF、Word、Excel、SVG、Markdown、CSV 等附件统一使用设置中的默认模型。
- 支持文件选择以及从资源管理器、微信等外部应用拖入附件。
- 默认模型不支持附件时返回明确错误，不静默切换模型。
- 工程参数建议通过差异卡确认后填入配置草稿，不自动运行。
- 科研目标、研究假设和参数建议通过确认弹窗批准后填入 Research State，并记录审计事件。
- PatchProposal 继续执行预览、审批和确认应用，Agent 不能直接写入工程文件。

### AI 科研流程

- 右栏统一为“研究目标、研究假设、参数配置、结果呈现”。
- 新建 Research 前要求命名，目标和假设可由用户填写或由 Agent 提供受限建议。
- 自主科研路线支持三套不同角度的候选方案，经过真实实验、结果比较、优选、问题诊断和下一轮建议。
- 所有实验继续遵守 Policy、Safety、Budget 和 F0–F3 审批链；失败实验保留为真实证据。

### 主题、环境与运行稳定性

- 浅色、完整暗色、跟随系统和自定义语义色板覆盖工作区、设置页、弹窗、日志、图表与 3D 容器。
- 支持背景、面板、文字、边框、强调色、状态色、图表色和对比度配置。
- MATLAB/Python 环境状态在客户端启动时初始化并缓存，模式切换不重复完整探测。
- 工程运行状态和事件订阅提升到保活层，切换“工程开发 / AI 科研”不会中断正在运行的 MATLAB 进程。
- 安装版 sidecar 显式打包 WebSocket 协议实现，工程与科研实时事件流可用。

## 安装包内容

发布附件：`TopOptPilot_2.0.1_x64-setup.exe`

安装包包含：

- TopOptPilot 桌面前端与 Rust 宿主；
- Python sidecar 与完整 Agent 服务；
- Node.js、Pi Agent、`.pi` 配置与技能；
- MCP 定义与 MATLAB MCP Server；
- MATLAB 2D/3D 工程求解器和案例预览资源；
- Python FEM 求解与科研 Policy/审批组件。

安装包不包含：

- MATLAB 本体或 MATLAB Runtime；
- `matlab/dist` 编译输出；
- API Key、授权头或模型权重；
- 用户聊天、运行日志、审批实例、实验结果或环境缓存。

## 系统与使用要求

1. Windows 10/11 x64。
2. 正式 MATLAB 求解需本机安装 MATLAB；客户端支持自动检测和手动选择 `matlab.exe`。
3. 在线 AI 需要在设置中配置 DashScope/Qwen 兼容服务、默认模型和 API Key。
4. 当前安装包未进行代码签名，Windows 首次运行可能显示 SmartScreen 提示。
5. 从旧版本升级时可直接运行新安装包；用户数据目录和已有 Research State 不会被源码仓库或 Release 覆盖。

## 验证结果

- Vitest：26 个测试文件、96 项通过。
- Python pytest：186 项通过。
- Rust：34 项通过。
- React production build、Python `compileall`、Rust `cargo fmt --check` 和 `git diff --check` 通过。
- 明暗主题下四种窗口尺寸的工程/科研 Composer、底栏开合和横向溢出验收通过。
- 正式打包 sidecar 的 WebSocket Research 事件流烟测通过。

## 完整性

- 文件名：`TopOptPilot_2.0.1_x64-setup.exe`
- 文件大小：`190,614,613` 字节（约 `181.78 MiB`）
- SHA-256：`F9D027C2DB012EE0542BD1F10B3CC22DC0F1769E496B89FD286EB0FBC36E3617`
- Authenticode：未签名（`NotSigned`）

下载后可使用 PowerShell 校验：

```powershell
Get-FileHash .\TopOptPilot_2.0.1_x64-setup.exe -Algorithm SHA256
```
