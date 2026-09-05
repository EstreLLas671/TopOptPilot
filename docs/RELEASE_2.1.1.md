# TopOptPilot 2.1.1 发布说明

发布日期：2026-09-05  
发布类型：稳定修复版（Windows x64）  
项目地址：https://github.com/EstreLLas671/TopOptPilot  
Release Tag：`v2.1.1`

## 一、版本摘要

TopOptPilot 2.1.1 重点修复了二维/三维拓扑优化结果普遍灰度过高的问题，并统一了 Python、MATLAB 工程链路和 MATLAB MCP 链路的投影参数、连续化控制和收敛状态语义。本版本同时更新桌面客户端版本号并重新生成 Windows NSIS 安装包。

## 二、核心修复

### 1. 修复高灰度优化结果

- MATLAB 2D/3D 工程求解器支持并实际使用 Heaviside 投影；
- 桌面 MATLAB 配置完整传递 `beta`、`beta_max`、`projection`、`controller`、`move_start` 和 `move_end`；
- Python 2D/3D 求解链路统一 `beta` 起始值、`beta_max` 上限和周期连续化策略；
- 默认连续化上限从过低的值提高到适合深度优化的范围，避免所有工况停留在未锐化 SIMP 解；
- 灰度率按最终物理密度和有效设计域计算，不再把原始设计变量误当成最终物理结果；
- MATLAB 每轮快照、最终结果和前端显示使用同一灰度率定义。

### 2. 修复收敛状态误报

- 达到最大迭代次数但未满足收敛条件时，保持 `max_iter`/未收敛状态；
- Python 2D、Python 3D 和 MATLAB 结果均发布真实 `converged` 字段；
- 前端不再把振荡或撞到移动限幅的结果显示为已收敛。

### 3. 修复 3D 结果统计

- 3D 最终体积分数改为使用投影后的物理密度；
- L 型等有效域计算排除域外单元；
- 3D MATLAB/Python 快照和结果清单保持维度、掩码和物理密度一致。

### 4. 发布与运行时一致性

- Python 服务、FastAPI、桌面前端、Tauri、Rust 包和发布审计版本统一为 `2.1.1`；
- 发布审计自动查找 `TopOptPilot_2.1.1_x64-setup.exe`；
- 安装包包含当前修复后的 MATLAB 工程求解器、MCP 资源和 Python sidecar。

## 三、验证结果

### 自动化测试

| 检查项 | 结果 |
|---|---:|
| Python 测试 | **277 passed, 6 skipped** |
| 桌面端 Vitest | **114 passed** |
| 灰度率/快照/MATLAB 桥接回归 | **25 passed** |
| TypeScript + Vite 生产构建 | 通过 |
| 离线发布审计 | `offline_release_ready: true` |
| Tauri Rust release 构建 | 通过 |
| NSIS 安装包构建 | 通过 |

测试中的 6 个 skipped 项为需要外部在线服务或特定环境的可选检查，不影响离线发布门禁。

## 四、安装包

文件名：`TopOptPilot_2.1.1_x64-setup.exe`  
平台：Windows x64  
安装包大小：约 193 MB

GitHub Release 附件同时提供该安装包及本说明文档。下载后建议先校验 GitHub Release 页面提供的 SHA-256，再运行安装程序。

## 五、运行要求

- Windows 10/11 64 位；
- 正式 MATLAB 工程求解需要本机安装 MATLAB，推荐 R2024b；
- 标准安装包不包含 MATLAB 本体或 MATLAB Runtime；
- 在线 AI 功能需要用户自行配置兼容的模型服务和 API Key；
- 未进行商业代码签名时，Windows SmartScreen 可能显示“未知发布者”，请以 SHA-256 校验为准。

## 六、已知限制

- 在线 Qwen 发布门禁需要网络和有效凭据，本次版本验证采用离线发布审计；
- 大网格 3D 求解会消耗较多内存和时间；
- NSIS 安装包未进行商业代码签名；
- MATLAB 版本差异可能导致局部数值性能差异，应以客户端实际探测结果为准。

## 七、升级建议

1. 关闭正在运行的旧版 TopOptPilot；
2. 安装 2.1.1；
3. 重新运行原有工况，不建议直接把旧版本的中间结果当作新版本结果；
4. 对关键工程方案保存最终结果、参数快照、灰度率、收敛状态和报告；
5. 如需反馈问题，请附版本号、求解维度、工况、网格参数和错误信息，不要上传包含 API Key 的日志。