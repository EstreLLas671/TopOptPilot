# TopOptPilot 开发版验证记录

日期：2026-08-23
目标分支：`TopOptPilot-v2-融合`
提交：`5efaa57 test: record v2 release audit status`

## 已通过

| 门禁 | 结果 |
|---|---|
| Python 回归测试 | `29 passed` |
| React/Vitest | `1 file / 2 tests passed` |
| React/Vite 生产构建 | 成功，1603 modules |
| Rust 单元测试 | `3 passed` |
| Python compileall | 通过 |
| `git diff --check` | 通过 |
| PyInstaller sidecar | 成功，`topoptpilot-backend.exe` 122,378,056 bytes |
| sidecar 握手与鉴权健康检查 | 成功，`/api/engineering/health` 返回 `status=ok`、`version=2.0.0` |
| 打包 sidecar Python FEM | 成功完成 1 次真实运行，生成 `result.json`、`density.csv`、`history.json`、快照和 SHA-256 |
| Tauri release 壳 | 成功，`desktop/src-tauri/target/release/topoptpilot.exe` 9,042,944 bytes；最小启动检查通过 |

## 尚未达到正式发布门禁

以下是实际阻塞项，不以 Safe Mode、演示数据或 Python 回退替代：

1. `vendor/matlab-mcp-server/matlab-mcp-server-windows-x64.exe` 尚未提供，因此 F3 MATLAB MCP 无法验收。
2. 编译 MATLAB Runtime 求解器及其 DLL 尚未提供，`compiled-runtime` lane 未完成干净机验证。
3. 受支持本机 MATLAB 的真实工程运行和 F3 真实执行尚未完成干净 Windows 验收。
4. `.pi`、`mcp`、`node_modules` 的完整可分发资源尚未形成正式 bundle；资源脚本会在缺失 MATLAB MCP vendor 时明确失败。
5. Tauri NSIS 安装包、干净 Windows 安装/升级/卸载、sidecar 与 MATLAB 子进程清理尚未验收。
6. 在线 Qwen/Pi 发布审计未通过；当前 `release_audit.json` 的 `release_ready` 和 `offline_release_ready` 均为 `false`。

## 可复现命令

```powershell
.venv\Scripts\python.exe -m pytest tests -q
npm --prefix desktop test -- --run
npm --prefix desktop run build
D:\Tools\Cargo\bin\cargo.exe test --manifest-path desktop\src-tauri\Cargo.toml
.venv\Scripts\python.exe -m compileall -q topoptpilot_desktop topoptpilot solver
git diff --check
$env:PATH = "D:\Tools\Cargo\bin;$env:PATH"
npm --prefix desktop run tauri build -- --no-bundle
```

开发版制品：

```text
build/desktop-sidecar/topoptpilot-backend.exe
desktop/src-tauri/target/release/topoptpilot.exe
```

本记录不改变旧版 `TopOptPilot`、`TopOptPilot-main` 或 `topopt_pilot` 目录，也不宣称 v2 已具备独立安装能力。

## 追加验证（23:15 后）

由于本轮继续接入 Runtime 竞态保护和三栏布局，最新 fresh 证据以以下结果为准：

- Python：`98 passed`。
- React/Vitest：`10 files / 35 tests passed`。
- React/Vite 生产构建：成功，输出包含布局 CSS 与双工作区。
- Rust：`27 passed`；`cargo fmt -- --check` 通过。
- Tauri 无打包 release 壳：`topoptpilot.exe` 成功构建。
- 开发构建重新生成 `build/desktop-sidecar/topoptpilot-backend.exe`；PyInstaller 有已知 hidden import 警告但构建完成。
- 离线 release audit：`offline_release_ready=false`；在线审计因 Pi RPC `get_state` 超时失败。

旧表格中的 29/2/3 项结果是历史阶段证据，不代表当前门禁；正式发布限制保持不变。
## 离线发布门禁与 NSIS（2026-08-24 00:34）

本轮已完成真正的 Tauri NSIS bundle，不再只是 `--no-bundle` 壳：

- 安装包：`desktop/src-tauri/target/release/bundle/nsis/TopOptPilot_2.0.0_x64-setup.exe`
- 大小：`168,293,346 bytes`
- SHA-256：`93225D671827D5D64DEE580979B7E3CAB43BC98B469CC269D73CF74363903445`
- 产品版本：`2.0.0`
- Authenticode：`NotSigned`，因此尚不作为已签名正式 Release。

打包资源已经包含 Python sidecar、Node 24.14.0、Pi 0.84.2、MCP 源码、MathWorks MATLAB MCP Windows x64 和 MATLAB 工程源码。MATLAB MCP 二进制 SHA-256 为 `F6ED9C4E04B25BEA4B5F52176202BDB1E3D4AF1BFBE91B2D90EB020129ED8228`，Authenticode 有效、签名者为 The MathWorks, Inc.；正式对外分发前仍需确认相应再分发许可。

资源 staging 已排除 `*.codex-*`、`*.codex-original`、`*.codex-replace`、`*.bad` 和 `.tmp-*`，正式 bundle 的 MATLAB 资源中未发现工作区辅助文件。

最新离线审计：

```json
{
  "offline_release_ready": true,
  "release_ready": false,
  "online_qwen": {
    "pass": null,
    "skipped": true
  }
}
```

离线审计已通过 desktop、2D/3D MATLAB MCP、F3 MATLAB provenance、baseline 和 Safe Mode。在线 `release_ready` 仍为 `false`，因为本轮没有通过 Qwen/Pi 在线门禁；此外编译 MATLAB Runtime 制品、安装包签名和干净 Windows 安装/升级/卸载矩阵仍需独立验收。
## 当前主机安装烟雾验证（2026-08-24）

使用 NSIS 标准静默参数将安装包部署到工作区内隔离目录 `.tmp-install-smoke`，结果如下：

- 静默安装退出码：`0`。
- 安装目录包含 `topoptpilot.exe`、`uninstall.exe` 和完整 `resources/`。
- 已安装 Tauri 主进程、WebView2 和 PyInstaller sidecar 均可冷启动。
- sidecar 实际回环端口对无令牌请求返回 `401`，说明令牌鉴权生效；Tauri 主进程保持响应。
- 关闭 Tauri 后，主进程与两级 PyInstaller sidecar 进程树均退出，无残留进程。
- 静默卸载退出码：`0`，隔离安装目录已删除。

该结果只证明当前开发主机上的安装、启动、鉴权、进程清理和卸载烟雾链路；不能替代计划要求的全新 Windows、有/无 MATLAB、有/无 Runtime 等干净机矩阵。

## 2026-08-24 Runtime 修复、标准版重建与安装烟雾

本节覆盖本轮新鲜命令，不替代干净 Windows 验收。

### Runtime 工程求解

- MATLAB：`D:\Tools\matlab\MATLAB R2024b(64bit)`。
- Compiler 重建退出码 `0`；`MCRSmoke.exe` 退出码 `0`，输出 `TOPOPTPILOT_MCR_SMOKE_OK`。
- `TopOptSolver.exe`：8×4×3、2 轮，退出码 `0`；`status.json` 为 `completed`。
- 结果目录：`.tmp-runtime-e2e-fixed`；生成 `result.mat`、结果摘要/清单、最终密度/应力、2 轮快照和快照清单，共 13 个文件。
- `solver.log` 扫描 `warning|error|fclose|错误使用`：无匹配。

### Runtime 分发边界

- `-RuntimePackage` 只接受包含 `mclmcrrt*.dll` 和 `bin/win64/Uninstall_MATLAB_Runtime.exe` 的 standalone MATLAB Runtime 根目录；完整 MATLAB 安装不能直接复制为 Runtime 分发包。
- Runtime staging manifest 记录 Runtime 根、DLL、solver 相对路径和 SHA-256；Python profile 在注册前校验路径、摘要和 solver allowlist。
- 标准版构建不包含 `resources/runtime`；当前主机未发现可再分发 MATLAB Runtime ZIP/MSI/DLL，因此未生成 Runtime 版安装包，也未宣称无 MATLAB 独立安装能力。

### 标准版 NSIS 与安装烟雾

- 安装包：`dist/TopOptPilot-v2-Setup-x64.exe`。
- 大小：`168,944,010` bytes。
- SHA-256：`8F742D46E7B51C8BEDE0D609C3AC423558FBBB56E15CB4CEE89F174C76CB4CFD`。
- Authenticode：`NotSigned`。
- 静默安装退出码 `0`；Tauri、WebView2 和 sidecar 启动；sidecar 未授权请求返回 `401`；关闭后本次进程树无残留；静默卸载退出码 `0`；隔离目录已删除。

### 本轮门禁

```text
Python pytest: 111 passed
React/Vitest: 10 files / 36 tests passed
Vite build: success
Rust: 27 passed
cargo fmt -- --check: pass
## 2026-08-24 Runtime 修复、标准版重建与安装烟雾

本节覆盖本轮新鲜命令，不替代干净 Windows 验收。

### Runtime 工程求解

- MATLAB：`D:\Tools\matlab\MATLAB R2024b(64bit)`。
- Compiler 重建命令：`matlab.exe -wait -batch "cd('F:/Other/揭榜挂帅/TopOptPilot/matlab/engineering'); build_solver"`，退出码 `0`。
- `MCRSmoke.exe`：退出码 `0`，输出 `TOPOPTPILOT_MCR_SMOKE_OK`。
- `TopOptSolver.exe`：8×4×3、2 轮，退出码 `0`；`status.json` 为 `completed`。
- 结果目录：`.tmp-runtime-e2e-fixed`；生成 `result.mat`、`result_summary.json`、`result_manifest.json`、最终密度/应力、2 轮快照和 `snapshots/manifest.json`，共 13 个文件。
- `solver.log` 扫描 `warning|error|fclose|错误使用`：无匹配。

### Runtime 分发边界

- `-RuntimePackage` 只接受包含 `mclmcrrt*.dll` 和 `bin/win64/Uninstall_MATLAB_Runtime.exe` 的 standalone MATLAB Runtime 根目录；完整 MATLAB 安装不能直接复制为 Runtime 分发包。
- Runtime staging manifest 记录 Runtime 根、DLL、solver 相对路径和 SHA-256；Python profile 在注册前校验路径、摘要和 solver allowlist。
- 标准版构建不包含 `resources/runtime`；当前主机未发现可再分发 MATLAB Runtime ZIP/MSI/DLL，因此未生成 Runtime 版安装包，也未宣称无 MATLAB 独立安装能力。

### 标准版 NSIS 与安装烟雾

- 安装包：`dist/TopOptPilot-v2-Setup-x64.exe`。
- 大小：`168,944,010` bytes。
- SHA-256：`8F742D46E7B51C8BEDE0D609C3AC423558FBBB56E15CB4CEE89F174C76CB4CFD`。
- Authenticode：`NotSigned`。
- 静默安装退出码 `0`；Tauri、WebView2 和 sidecar 启动；sidecar 未授权请求返回 `401`；关闭后本次进程树无残留；静默卸载退出码 `0`；隔离目录已删除。

### 本轮门禁
