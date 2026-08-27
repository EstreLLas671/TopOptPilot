# TopOptPilot 2.0.0 发布说明

发布日期：2026-08-27

## 核心能力

- 紧凑三栏工程开发与独立 AI 科研工作区。
- MATLAB 为默认正式求解后端，Python FEM 可选。
- 接入真实 MATLAB 2D/3D 逐轮 PNG、密度和 Von Mises 应力数据。
- 3D 密度与应力支持旋转、缩放、平移、重置和全屏。
- 工程聊天和科研聊天支持图片、PDF、Word、Excel、SVG、Markdown、CSV 等附件及外部拖拽。
- 所有聊天形式统一使用设置中的默认模型。
- 工程聊天草稿按项目和会话保存。
- 工程补丁保持 PatchProposal 预览、审批和确认应用边界。
- 工程运行可显式命名并转为科研基线；科研实验继续遵守 Policy、Budget 和 F0–F3 审批。

## 安装包内容

包含完整 TopOptPilot 后端 Agent、Node/Pi 运行资源、MATLAB MCP、2D/3D MATLAB 求解器与案例资源。安装包不包含 MATLAB 本体、MATLAB Runtime、API Key、模型权重、聊天数据、日志或审批运行记录。

## 使用前准备

1. Windows 10/11 x64。
2. MATLAB 正式求解需本机安装 MATLAB；应用支持自动检测和手动选择路径。
3. 在线 AI 需要在设置中配置有效的 DashScope/Qwen 兼容服务信息。
4. 当前安装包未签名，Windows 可能显示 SmartScreen 提示。

## 完整性

发布附件：`TopOptPilot_2.0.0_x64-setup.exe`

SHA-256：`C7E2BF2BCEE45E8B6EBE3D25FC8573D09F2D4723E850C099DE3A6E5216737CE3`