# TopOptPilot 当前实施状态

更新日期：2026-08-23

## 已完成

- 独立 Git 仓库与分支：`codex/topoptpilot-fusion`。
- TopOptPilot 权威上游冻结为 `https://github.com/wuliaoonly/TopOptPilot` 的 `main`，基线提交见 `docs/baseline/`。
- 产品元数据统一为：`TopOptPilot`、版本 `2.0.0`、Tauri identifier `com.topoptpilot.v2`。
- Python sidecar 统一入口：`topoptpilot_desktop.api.app:app`，保留 TopOptPilot Research API 并挂载 Engineering API。
- `RunArtifact`、`ArtifactRef`、`ErrorEnvelope` 已建立，完成态必须有真实 solver provenance 和输出文件；失败态必须携带错误信封。
- 工程 MATLAB 发现、Runtime 结构判定和严格 `-wait -batch` 探针已迁移；探针失败统一为 `MATLAB_INFRASTRUCTURE`。
- React 双工作区已建立：工程开发 / AI 科研。默认浅色、蓝色强调、紧凑 IDE 布局。
- Tauri 项目文件命令已建立：路径根约束、扩展名白名单、UTF-8、原子保存、外部摘要冲突、补丁基线检查。
- `webview_*` 已实现受限子 WebView：仅允许 http/https、默认 localhost/127.0.0.1、禁止凭据和任意外部主机。

## 当前验证证据

```text
Python: .venv\Scripts\python.exe -m pytest tests -q      29 passed
React:  npm --prefix desktop test                         2 passed
React:  npm --prefix desktop run build                   success
Rust:   cargo test --manifest-path desktop/src-tauri/Cargo.toml 6 passed
```

Rust 工具链已安装在：

- `D:\Tools\VisualStudioBuildTools2022`（MSVC 主体；Windows SDK 仍由微软安装到系统 Windows Kits）
- `D:\Tools\Rustup`
- `D:\Tools\Cargo`

本机 WebView2 已检测到 `151.0.4129.101`。

## 尚未通过的发布门禁

- `topoptpilot.release_audit` 在线模式因 Pi RPC `get_state` 超时失败；当前不能证明有效 Qwen/Pi 在线链路。
- 离线审计返回 `offline_release_ready=false`；科研 Release 尚未就绪。
- 尚未完成真实本机 MATLAB 单次工程求解、MATLAB MCP F3、编译 Runtime 和干净 Windows 安装矩阵。
- `webview_create/navigate` 已完成协议、主机、凭据白名单；弹窗、下载策略仍需在正式发布前补充 UI 级验证。
- `patch_apply` 已校验 hunk 范围、上下文、删除行、计数和换行，并支持多文件预校验与回滚。

以上限制均被保留为明确失败或未探测状态，没有使用演示数据冒充真实求解结果。
- 浏览器视觉验收：Tauri release 壳已构建并完成最小生命周期启动；当前环境未完成真实窗口截图验收。

## 本轮新增（2026-08-23）

- 工程 Python FEM runs 已接通：队列、运行状态、取消、事件回放与 WebSocket 流。
- 每次真实求解写入 `result.json`、`density.csv`、`history.json` 和迭代快照，并计算 SHA-256 制品引用。
- 工程报告导出为 `report.md`，仅允许终态运行导出。
- MATLAB 文件终端桥已迁移：会话目录、原子命令文件、结果轮询、stop 和命令大小/空命令校验；未提供可验证 MATLAB 时状态明确为 `waiting-matlab`，不伪装为已连接。
- React 工程工作区已接入真实 runs、取消、报告、事件流和终端 API；Python FEM 运行按钮不调用科研执行链路。

本轮新增测试：Python 全部测试 `19 passed`，React `2 passed`，React build 成功。尚未完成本机 MATLAB 真运行、编译 Runtime、Research 完整交互和安装包发布门禁。
- AI 科研工作区已增加 Research 创建入口、待审批 Policy 卡片、批准/拒绝动作和刷新；仍复用 TopOptPilot 既有 ResearchService、Policy 与 Pi session。

## 本阶段新增（2026-08-23 12:40）

- 将工程 MATLAB 入口、终端桥和当前 TopOpt-3D `.m` 源码纳入 `matlab/engineering`，不复制运行输出和缓存。
- `local-matlab` lane：使用显式安装发现、严格 batch probe、`run_topopt_job.m` 和 `status.json/result_summary.json` 契约；探针或求解失败记录 `MATLAB_INFRASTRUCTURE`，不回退 Python。
- `compiled-runtime` lane：使用 `TOPOPTPILOT_RUNTIME_SOLVER` 指定的已验证求解器；缺失、退出失败或结果不完整记录 Runtime 基础设施错误。
- `matlab-mcp` 从工程 runs 明确拒绝，只能走 ResearchService、Policy、审批和 MATLAB MCP。
- 科研结果新增统一制品索引、路径越界保护、Pareto 和比较 API；科研面板显示 experiment provenance 和制品数量。
- Tauri 子 WebView 已启用受限生命周期：仅允许 `http/https`、默认 `localhost/127.0.0.1`，禁止凭据和任意外部主机，增加 Rust 安全测试。

本阶段验证：Python `29 passed`，React `2 passed`，Vite build 成功，Rust `3 passed`，compileall 和 `git diff --check` 通过。真实本机 MATLAB、已编译 Runtime、F3 MCP、在线 Pi/Qwen 和正式安装包仍需真实环境门禁。

## 本轮继续开发（2026-08-23 23:20）

- 修复工程 Runtime 探测 helper 的 TypeScript 语法回归，并接入 generation/lane/root/solver 上下文校验、重复探测 busy guard、lane 切换失效和陈旧响应丢弃。
- 工程开发与 AI 科研两个工作区均已迁移到 `ResizableWorkspaceLayout`：左栏、右栏、底栏支持 pointer 拖拽调整；三个面板可独立隐藏/恢复；工程与科研分别使用 localStorage key 持久化布局；提供当前工作区布局重置。
- 保留原 TopOptPilot 的默认尺寸约束：左栏 280（240–420）、右栏 380（320–520）、底栏 300（180–520），窄屏保留恢复入口。
- Python FEM 终态运行在写入 `result.json` 前补充真实 solver provenance；Runtime 错误事件使用结构化错误码；公开 compiled-runtime API 无 profile 时返回 422，不回退 Python。
- 工程 runs、MATLAB 终端、ResearchService 与 Tauri release sidecar 已统一到 `%LOCALAPPDATA%\\TopOptPilot`（可由 `TOPPILOT_DATA_DIR`/`TOPOPTPILOT_DATA_DIR` 显式覆盖），不再分裂为旧 `topoptpilot/storage`。

本轮 fresh 验证：

- React Vitest：`35 passed`；Vite build：成功（仅 Monaco 动态 chunk 大小提示）。
- Python：`98 passed`。
- Rust：`27 passed`；`cargo fmt -- --check`：通过。
- Tauri 无打包 release 壳：`desktop/src-tauri/target/release/topoptpilot.exe` 已构建。
- `git diff --check`：通过（仅 CRLF 转换提示）。

发布限制仍未解除：

- `topoptpilot.release_audit --offline` 返回 `offline_release_ready=false`，原因包括审计脚本仍期待正式 NSIS 制品、MATLAB MCP server 二进制缺失、F3 无法真实执行。
- 在线审计因 Pi RPC `get_state` 超时失败；不能宣称在线 Qwen/Pi 通过。
- 尚未完成真实本机 MATLAB 工程求解、编译 Runtime E2E、MATLAB MCP/F3、NSIS 安装包和干净 Windows 安装/升级/卸载验证。
## 2026-08-24 最终开发板更新

- 已补入签名有效的 MathWorks MATLAB MCP Windows x64 资源，并通过真实 2D/3D MCP 离线审计。
- 已按锁文件准备 Node/Pi 运行依赖，Node 24.14.0 与 Pi 0.84.2 可执行 `--help` 冷启动。
- 已生成 Tauri NSIS：`TopOptPilot_2.0.0_x64-setup.exe`，168,293,346 bytes，SHA-256 `93225D671827D5D64DEE580979B7E3CAB43BC98B469CC269D73CF74363903445`。
- 最新门禁：Python `104 passed`、React `35 passed`、Rust `27 passed`、离线 release audit `offline_release_ready=true`。
- 尚未完成：在线 Qwen/Pi 门禁、编译 MATLAB Runtime 版、安装包代码签名和干净 Windows 安装矩阵。安装包当前为 `NotSigned`，不得描述为正式签名 Release。
## 2026-08-24 Runtime 清洁 E2E 与分发边界更新

- 修复 `matlab/engineering/run_topopt_job.m` 的二进制 payload 句柄生命周期：`onCleanup` 现在是唯一关闭路径，避免快照完成后重复 `fclose`。
- 新增 MATLAB snapshot contract 回归测试；当前该文件 `3 passed`。
- 使用本机 MATLAB R2024b Compiler 重新生成 `MCRSmoke.exe` 与 `TopOptSolver.exe`。
- 真实 Runtime 最小求解（8×4×3、2 轮）退出码为 `0`，`status.json.state=completed`，生成 13 个结果/快照制品；`solver.log` 无 warning/error/fclose 匹配。
- `scripts/build_desktop.ps1` 新增显式 `-RuntimePackage -RuntimeRoot -RuntimeSolver` staging：强制检查 `mclmcrrt*.dll`、`Uninstall_MATLAB_Runtime.exe`、solver `.exe`、路径边界和 SHA-256 manifest；完整 MATLAB 安装会被拒绝，不能冒充独立 Runtime。
- `RuntimeProfileStore` 支持 `resources/runtime/runtime-manifest.json` 的路径与 SHA-256 校验、bundled profile 注册和篡改拒绝；标准版无 manifest 时明确返回不可用。
- Engineering API 新增 `/api/engineering/runtime/bundled`；工程前端启动时只接受后端 `ready + usable + profileId` 的 bundled Runtime profile，并保留原有 lane 竞态保护。
- 新标准版 NSIS 已重建：`dist/TopOptPilot-v2-Setup-x64.exe`，168,944,010 bytes，SHA-256 `8F742D46E7B51C8BEDE0D609C3AC423558FBBB56E15CB4CEE89F174C76CB4CFD`；标准版确认不含 `resources/runtime`，Authenticode 为 `NotSigned`。
- 本轮新鲜门禁：Python `111 passed`；React `36 passed`；Vite build 成功；Rust `27 passed`；`cargo fmt -- --check` 通过；Python compileall 通过；离线 audit `offline_release_ready=true`、`release_ready=false`。
- 最新安装烟雾：静默安装退出 `0`，sidecar 未授权请求 `401`，关闭后本次进程树剩余 `0`，静默卸载退出 `0`，隔离目录已删除。
