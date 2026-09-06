# TopOptPilot：Tauri + React 融合实施计划

> 本文档冻结 2026-08-23 已批准的实施边界。实现过程使用测试驱动和分阶段验收，不以历史制品或说明文档代替当前验证。

## 目标

在独立目录中构建 TopOptPilot：使用 Tauri 2、React 19 和统一 Python sidecar，保留 TopOptPilot 的浅色紧凑 IDE、MATLAB/Runtime 工程链路、实时迭代和报告能力，并接入 TopOptPilot 的 ResearchService、Pi/Qwen、Policy、审批、预算、Evaluator 与 MATLAB MCP 科研链路。

## 冻结决策

- 原 TopOptPilot 与 TopOptPilot 目录只读，不在原目录实施功能改动。
- v2 默认中文、浅色、标准密度，保留暗色和自定义主题。
- 提供“工程开发”和“AI 科研”两个一级工作区。
- 工程助手只生成可审阅补丁；科研 Agent 只能使用科研工具白名单。
- 工程任务可用本机 MATLAB 或编译 Runtime；科研 F3 只能经 Policy、审批与 MATLAB MCP。
- 两条链路只在统一 `RunArtifact` 制品层汇合，不能互相绕过权限。
- v2 使用 `%LOCALAPPDATA%\TopOptPilot`，不迁移旧数据库或设置。
- RollbackManager、Paper-to-Plugin、FAISS 和 CUDA MEX MCP 在未真实实现前不暴露为可用功能。

## 阶段

1. 冻结并校验 TopOptPilot 与 TopOptPilot 源码基线。
2. 建立 TopOptPilot Tauri 外壳、视觉系统、双工作区与统一设置。
3. 实现受控项目文件 IDE 和工程助手补丁审批。
4. 迁移本机 MATLAB、编译 Runtime、终端、单次求解、快照和工程报告。
5. 接入 ResearchService、Pi/Qwen、Policy、实验、审批、比较、报告与复现包。
6. 统一制品、错误协议、跨工作区跳转和受限子 WebView。
7. 依次完成开发版、NSIS 安装包和干净 Windows 验收。

## 验收命令

```powershell
npm --prefix desktop test
npm --prefix desktop run build
cargo test --manifest-path desktop/src-tauri/Cargo.toml
py -3 -m pytest tests -q
py -3 -m topoptpilot.release_audit
```

只有真实求解器结果可以标记为 `completed`。MATLAB、Runtime、MCP、模型凭据或干净环境门禁不可用时，必须记录为环境限制或基础设施失败，不得使用演示结果替代。