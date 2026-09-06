# TopOptPilot 无界面命令手册：topoptctl

## 目的与能力边界

topoptctl 是 TopOptPilot 的仓库级、机器可读命令入口。它启动一个仅监听 127.0.0.1 的认证 Sidecar，因此 Codex、Pi、CI、PowerShell 脚本或其他终端 Agent 无需打开桌面窗口，也能安全使用当前工程已经验证的能力。

它不是通用 Shell、MATLAB 命令桥，不能执行任意 MATLAB 代码，不能提交任意 API 工具名，不能指定求解输出路径，也不会把 API Key 或 Sidecar Token 写入命令行、JSON 输出、工程状态文件、报告或导出包。

当前真实求解边界如下：

- Engineering 命名空间：本机 MATLAB 的受控二维或三维工程基线。二维 MATLAB 任务会产出真实迭代快照、最终密度图和收敛图。
- Research 命名空间：仅能走 Research State 与 Policy 的白名单流程。它不能绕过 intent、preview、审批或约束。
- Engineering 的已完成运行可导入为 Research 基线证据；它本身不是正式 Policy 实验。
- 当前任务 Schema 只支持预设工况、规范化参数和材料字段。请不要把任意载荷、手绘几何、文件路径或 MATLAB 脚本伪装成参数。

## 安全模型

1. Sidecar 只绑定 127.0.0.1，且每个 daemon 会话使用随机令牌。
2. 会话令牌和 Qwen 凭据只保存在 Windows Credential Manager；headless-session.json 仅保存 PID、端口、数据目录和会话 ID。
3. daemon stop 会先验证 Loopback API 会话身份，再核验该 PID 的命令行确实是 TopOptPilot Sidecar，最后才终止进程树。
4. 启动 MATLAB、取消 MATLAB、停止 daemon、提交 Policy Proposal、批准人工决策都要求明确的 --confirm。
5. 每个导出的求解文件都要与服务器清单内的 SHA-256 对比；哈希不匹配即失败，不会伪装为成功导出。
6. 常规输出固定为 JSON envelope。外部 Agent 应只根据 ok、status、data 和 error.code 决策，不能从自然语言猜测状态。

## 前置条件

- 在 TopOptPilot 仓库根目录执行命令。
- 可使用 Python 3；首次克隆可直接使用下方受限引导器创建工程根目录下的 `.venv`。
- 若要运行本机 MATLAB 基线，MATLAB 根目录中必须存在 bin/matlab.exe。
- 若要使用 Qwen/Pi，必须有经过授权的 Qwen OpenAI-compatible 凭据。凭据不得写入仓库、任务 JSON、终端历史、截图或报告。
- 对生产数据使用一个独立 data directory，避免和桌面应用的长期数据混用。

### 首次克隆的安全初始化

在仓库根目录执行：

    pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_headless.ps1

该脚本只创建或复用仓库内的 `.venv`、安装 `requirements.txt`，并且仅在根目录 Pi 运行时不存在时执行 `npm ci --ignore-scripts --no-audit --fund=false`。它不写入或读取 Qwen/API 凭据，不启动 Sidecar，不启动 MATLAB，也不创建 Engineering/Research 任务。默认不会替换已有的 `node_modules`；如果它被发现为不完整，先人工检查，再明确传入 `-ReinstallPiRuntime`。

离线检查或 CI 可以跳过两个安装步骤并获取单行 JSON：

    pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_headless.ps1 -SkipPythonDependencies -SkipPiRuntime -Json

完成后再运行 `topoptctl doctor`；引导器本身不代替健康检查，也不隐式探测 MATLAB 或 Qwen。

下面示例以 PowerShell 为例。请把路径替换为你自己的路径。

    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    $OutputEncoding = [Console]::OutputEncoding
    Set-Location D:\work\TopOptPilot
    $state = "D:\TopOptPilotData\headless"
    .\topoptctl.cmd --data-dir $state daemon start

首次运行会创建受控 Sidecar。启动器和上述 PowerShell 设置改善交互显示；更重要的是，默认 JSON 模式将非 ASCII 字符写成标准 JSON Unicode 转义，因此 ConvertFrom-Json 或任何合规 JSON 解析器会在不同 Windows 代码页下恢复正确的中文路径和状态。后续命令均加同一个 --data-dir。

## 设置 MATLAB 与 Qwen

先保存 MATLAB 根目录并刷新工程环境。此操作会做受控 MATLAB 探测，但不会启动拓扑优化任务。

    .\topoptctl.cmd --data-dir $state configure matlab --root "D:\MATLAB"

设置非敏感的模型地址与模型名：

    .\topoptctl.cmd --data-dir $state configure qwen --base-url "https://your-endpoint/compatible-mode/v1" --model "your-approved-model" --restart-pi

首次无界面保存凭据时，只能经标准输入写入 Windows Credential Manager，绝不能把 Key 放在命令行参数中。请让你的企业密钥管理器、安全输入控件或 Agent Secret Store 将明文仅通过标准输入提供给下列命令：

    <secure-secret-provider> | .\topoptctl.cmd --data-dir $state configure qwen-key --stdin

也可以在当前受控进程生命周期内使用 DASHSCOPE_API_KEY 环境变量作为一次性覆盖。不要把它写进 .env、PowerShell Profile、仓库脚本或任务 JSON。

显式验证两个外部依赖：

    .\topoptctl.cmd --data-dir $state doctor --probe-matlab --check-qwen

不带选项的 doctor 是只读诊断，不启动 MATLAB 求解器、不请求 Qwen：

    .\topoptctl.cmd --data-dir $state doctor

## 极小二维真实闭环

仓库提供了一个适合验证通路而非验证结构质量的 20 x 10、四迭代悬臂梁样例：

    $task = ".\examples\topoptctl\mini-2d-cantilever.json"
    .\topoptctl.cmd --data-dir $state engineering plan --config $task --time-limit 300

plan 会走与真实提交相同的服务端 Schema 校验，但 sideEffect 必须为 none。确认 JSON 返回 status=validated 后，显式启动 MATLAB：

    .\topoptctl.cmd --data-dir $state engineering run start --config $task --time-limit 300 --confirm

从 JSON 的 data.run.runId 保存真实运行 ID，然后轮询或读取事件：

    .\topoptctl.cmd --data-dir $state engineering run wait eng-<32-hex> --timeout 300
    .\topoptctl.cmd --data-dir $state engineering run events eng-<32-hex>

完成的二维 MATLAB 基线必须有真实 result.mat、result.json、density.csv、density.png、convergence.png 和每轮 snapshot。请导出到一个已存在、专用的空父目录：

    New-Item -ItemType Directory -Force "D:\TopOptPilotExports" | Out-Null
    .\topoptctl.cmd --data-dir $state engineering export eng-<32-hex> --output-dir "D:\TopOptPilotExports"

导出的 run 子目录内有 export-manifest.json。它列出每个文件的 SHA-256，外部 Agent 可以读取该清单后再打开 density.png 和 convergence.png。四迭代样例仅验证完整数据流，通常灰度比例很高，不能宣称为收敛或高质量设计。

## 取消测试

取消不是删除证据。使用较大的受控样例启动一个真实运行，读取至少一个事件或 snapshot 后再取消：

    $cancelTask = ".\examples\topoptctl\cancel-2d-cantilever.json"
    .\topoptctl.cmd --data-dir $state engineering run start --config $cancelTask --time-limit 300 --confirm
    .\topoptctl.cmd --data-dir $state engineering run cancel eng-<32-hex> --confirm
    .\topoptctl.cmd --data-dir $state engineering run wait eng-<32-hex> --timeout 120

正确的最终状态是 cancelled，不是 completed。该运行可导出用于诊断，但不能作为已完成工程基线导入到 Research。

## 从真实工程证据进入 Policy

完成的 Engineering run 可以创建一个 Research 基线，但它不会自动提交实验：

    .\topoptctl.cmd --data-dir $state research from-engineering-run eng-<32-hex> --name "真实二维基线" --goal "以真实 MATLAB 基线为证据，按 Policy 比较参数" --budget 12

接下来只通过 Policy 命令组工作：

    .\topoptctl.cmd --data-dir $state research context MBB-001
    .\topoptctl.cmd --data-dir $state research propose MBB-001 --intent ESTABLISH_BASELINE
    .\topoptctl.cmd --data-dir $state research preview MBB-001 P-<proposal>

提交 Proposal 必须再次使用 --confirm，且 Research State 由服务端重新读取：

    .\topoptctl.cmd --data-dir $state research submit MBB-001 P-<proposal> --confirm

如果服务端产生人工审批项，只有用户或被明确授权的自动化可以批准：

    .\topoptctl.cmd --data-dir $state research approve D-<decision> --confirm

请特别区分 Engineering 与 Policy：当前 Engineering 2D MATLAB 真实运行的价值是工程基线证据；不要把它描述为 Policy F0/F1/F2/F3 正式实验结果。

## 命令组契约

| 命令组 | 可做的事 | 不可做的事 |
| --- | --- | --- |
| daemon | 启动、检查、验证后停止 loopback Sidecar | 连接远程 Sidecar 或终止未经核验的 PID |
| doctor | 检查配置、工程环境、可选 Qwen/MATLAB 探测 | 默认启动求解器或消耗 Qwen Token |
| configure | 保存 MATLAB 根目录、Qwen URL/模型、通过 stdin 保存 Key、显式联通性检查 | 在参数中传递 Key 或写入配置文件 |
| project | 创建 Research 项目、设置已验证优化配置 | 直接绕过 Policy 启动实验 |
| engineering | 验证、启动、查看、等待、取消、导出本机 MATLAB 基线 | 执行原始 MATLAB、任意路径导出、伪造完成状态 |
| research | 导入工程证据、读取上下文、编译 intent、preview、submit、approve、查看状态 | 调用未列入 Policy 的任意工具名 |

## JSON 结果与退出码

成功结果结构：

    {"ok":true,"status":"...","data":{...}}

失败结果结构：

    {"ok":false,"error":{"code":"...","message":"...","details":...}}

约定：

- 默认 --json 使用 ASCII 安全的 JSON Unicode 转义，适合 Codex、Pi、CI 与 PowerShell 管道；解析 JSON 后值仍是原始中文。--human 仅用于人工阅读。
- 退出码 0：命令完成。调用方仍应检查 data 内的运行状态，例如 cancelled、failed 或 timeout 不是成功求解。
- 退出码 2：输入、认证、会话、确认或 Policy 契约错误。
- 退出码 3：等待超时；不会中止后台运行，需调用 get、events 或 cancel 继续处置。
- status=completed 才表示 MATLAB Engineering run 已完成；status=cancelled、failed、timeout、paused 和 blocked 都不能被 UI 或 Agent 呈现为成功。

## 给 Codex、Pi 或其他 Agent 的调用约束

外部 Agent 应按以下顺序操作：

1. 新克隆仓库时先运行 `scripts/bootstrap_headless.ps1`；不把它当成凭据或 MATLAB 设置命令。
2. 运行 daemon status；未运行时才 daemon start。
3. 运行 doctor；只有用户授权时才附加 --probe-matlab 或 --check-qwen。
4. 将任务写成严格 JSON 数据，不生成 MATLAB 字符串。
5. 先 engineering plan；只有用户明确允许实际计算后，调用 run start --confirm。
6. 读取 wait/events/get 的 JSON，并将 runId 作为后续唯一引用。
7. 导出时只使用服务端清单，读取 export-manifest.json 后再使用图片或数值。
8. Research 阶段只使用 research 子命令。任何确认失败都应报告给用户，而不是补发 --confirm。

在无需继续后台服务时，显式停止本次 CLI 创建的 Sidecar：

    .\topoptctl.cmd --data-dir $state daemon stop --confirm

## CLI-Anything 的使用准则

当前 topoptctl 已覆盖 MATLAB 设置、Qwen 设置、工程创建与参数应用、真实运行、迭代证据、取消、带哈希导出和受 Policy 约束的 Research 路径，因此不应为了“自动化”引入一个能任意执行 CLI 的宽泛 Harness。

只有出现已经复现、且无法通过本命令白名单表示的高价值工作流时，才考虑用 CLI-Anything 辅助生成适配层。适配层必须保留本命令组的 allowlist、确认、loopback、凭据和导出哈希规则，并先通过安全审查和回归测试，不能替换核心 topoptctl。
