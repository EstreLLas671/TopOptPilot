# TopOptPilot

TopOptPilot 是面向二维/三维结构拓扑优化的 Windows 桌面客户端，将真实工程求解、AI 辅助开发和可审计科研实验整合到同一个工作台。

## 主要能力

### 工程开发

- 项目文件树、代码编辑、文件保存和受控补丁。
- MATLAB 为默认正式求解后端，Python FEM 可选。
- 支持 2D/3D、悬臂梁、MBB 梁、简支梁和 L 型支架工况。
- 支持材料预设、自定义材料、网格、体积分数、惩罚因子、滤波半径和迭代参数。
- 实时显示 MATLAB 命令行、逐轮 PNG、密度与 Von Mises 应力制品。
- 3D 密度和应力支持旋转、平移、滚轮缩放、重置和全屏。
- 支持运行结果、方案详情、双方案对照及报告导出。
- 工程结果只有在用户命名并确认后才会成为新的科研基线。

### AI 科研

- Research State、研究目标、默认实验参数和实验时间线。
- 真实 AI 对话、实验规划、审批状态、MATLAB/MCP 进度和结果分析。
- Policy、Safety、Budget 与 F0–F3 审批链。
- 失败实验、审批记录、证据索引、制品哈希和复现报告长期保存。
- 工程开发与 AI 科研状态相互隔离，不会自动把普通工程求解当作科研实验。

### AI 对话与附件

文本、PNG、JPEG、WebP、SVG、PDF、DOCX、XLSX、TXT、Markdown 和 CSV 统一使用设置中的默认模型。附件可通过选择文件或从资源管理器、微信等外部应用拖入。

默认模型不支持某种附件时，客户端会明确报告错误，不会静默切换模型或伪造回复。工程聊天草稿按项目和会话保存；代码只有在用户明确同意后才会发送给外部模型。

## 安装

在本仓库 [Releases](https://github.com/EstreLLas671/TopOptPilot/releases) 下载：

```text
TopOptPilot_2.0.0_x64-setup.exe
```

系统要求：

- Windows 10/11 x64。
- 使用正式 MATLAB 求解时，需要本机安装 MATLAB；客户端支持自动检测和手动选择路径。
- 在线 AI 需要在设置中配置有效的 DashScope/Qwen 兼容 API 地址、默认模型和 API Key。
- 当前安装包未进行代码签名，Windows 首次运行可能显示 SmartScreen 提示。

安装包包含 TopOptPilot 后端 Agent、Node/Pi、MATLAB MCP、2D/3D MATLAB 求解器和案例预览资源。安装包不包含 MATLAB 本体、MATLAB Runtime、API Key、Qwen 模型权重、用户聊天、审批记录或运行日志。

## 快速使用

1. 启动 TopOptPilot，默认进入“工程开发 → 聊天”。
2. 在左栏打开工程文件夹并选择文件。
3. 在右栏确认 MATLAB 环境；检测失败时手动选择 MATLAB 可执行文件。
4. 打开详细参数，选择 2D/3D、工况、材料和优化参数。
5. 点击运行。下栏会自动打开并显示真实求解器输出。
6. 在“迭代可视化”查看真实 MATLAB 逐轮图、密度和应力。
7. 在“结果”查看最终 2D/3D 结构、收敛历史和制品。
8. 如需科研闭环，点击创建科研基线、填写名称与目标，再进入“AI 科研”。

更详细的中文使用手册位于 `F:\Other\揭榜挂帅\README\TopOptPilot_使用说明.md`（开发机交付目录，不随仓库保存用户本地数据）。

## 源码结构

```text
TopOptPilot/
├── desktop/                 Tauri 2 + React 桌面前端与 Rust 宿主
├── idesktop_v2/             桌面 sidecar、工程 API、聊天和会话服务
├── topoptpilot/             AI 科研、Policy、Memory、Agent Runtime
├── agent/                   智能体与模型客户端
├── matlab/engineering/      TopOptPilot 2D/3D MATLAB 工程求解器
├── 求解器模块/              MATLAB MCP 权威求解器资源
├── mcp/                     MATLAB MCP 接口和工具定义
├── solver/                  Python FEM 求解器
├── .pi/                     Pi 运行配置、扩展和技能
├── tests/                   Python 回归测试
└── scripts/build_desktop.ps1 Windows 安装包构建脚本
```

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
npm install
npm --prefix desktop install
```

启动或构建前端：

```powershell
npm --prefix desktop run build
npm --prefix desktop test
```

构建完整 Windows 安装包：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts/build_desktop.ps1 `
  -SkipInstall `
  -PythonExe .\.venv\Scripts\python.exe
```

安装包输出到：

```text
desktop/src-tauri/target/release/bundle/nsis/
```

## 数据与安全边界

- 工程助手不能直接修改文件，只能生成 PatchProposal；应用前必须预览并确认。
- AI 科研实验不能绕过 Policy、Budget 和 F0–F3 审批。
- API Key、授权头和原始附件路径不得写入运行日志、普通设置或报告。
- 缺少真实 MATLAB 数据时，界面不会生成模拟密度、应力或迭代图。
- MATLAB MCP 故障不能回退为 Python 并宣称 F3 成功。
- 用户聊天、运行日志、审批运行记录和环境缓存不纳入源码仓库或 Release。

## 仓库内容策略

源码仓库保留实现、测试、MATLAB 求解器、前端案例资源、配置模板和构建脚本；以下内容通过 `.gitignore` 排除：

- `.venv/`、`node_modules/`、Rust `target/` 和其他构建目录；
- `.tmp/`、`.debug-data/`、`output/`、日志和测试临时文件；
- 用户对话、运行结果、审批运行记录和环境缓存；
- API Key、环境变量文件和本地凭据；
- 安装包本体。安装包只作为 GitHub Release 附件发布。

第三方可执行文件和依赖不直接提交到源码仓库；完整安装包由发布构建流程打入经验证的运行资源。

## 发布

当前桌面版本：`2.0.0`。

详细发布说明见 [docs/RELEASE_2.0.0.md](docs/RELEASE_2.0.0.md)。

## 许可证与第三方组件

使用或再分发前请分别确认本项目代码、MATLAB、Node、Pi、MATLAB MCP 以及其他第三方依赖的许可条款。MATLAB 本体与 MATLAB Runtime 不随本仓库或默认安装包分发。