# 2026-08-30：topoptctl 无界面真实 MATLAB 验证

## 目的

验证 TopOptPilot 可以不打开桌面窗口完成一条受控路径：

1. 启动 loopback Sidecar；
2. 写入并探测本机 MATLAB；
3. 配置 Qwen 非敏感连接信息，并以 Credential Manager 内凭据完成显式联通性检查；
4. 创建 Research 项目、应用二维配置并执行无副作用 plan；
5. 启动真实 MATLAB 2D 运行，读取真实迭代图；
6. 在另一个真实运行中执行取消；
7. 对完成的运行执行 SHA-256 验证导出；
8. 将完成的工程运行作为 Research 基线，验证 Policy context、intent 编译、preview 和确认闸门。

所有验证使用独立的 headless data directory，不复用桌面应用长期数据。Qwen Key 不写入命令、日志、报告、状态文件或本记录。

## 环境结果

| 组件 | 结果 |
| --- | --- |
| Python 运行时 | 已在隔离 .venv 中运行 |
| MATLAB | D:\MATLAB\bin\matlab.exe，R2024b，受控 batch 探测成功 |
| Pi Agent runtime | ready |
| Qwen OpenAI-compatible 连接 | 通过 Credential Manager 的显式检查，status=verified |
| Sidecar | 每会话随机 token、仅绑定 127.0.0.1、会话身份校验成功 |

## 完成的极小二维基线

输入为 examples/topoptctl/mini-2d-cantilever.json：

| 字段 | 实际值 |
| --- | --- |
| 维度 | 2D |
| 工况 | cantilever |
| 网格 | 20 x 10 |
| 体积分数 | 0.4 |
| 最大迭代 | 4 |
| 求解通道 | local-matlab，TopOpt_2D/topopt_main.m |
| Engineering run ID | eng-01d3dfebbdbf4b55ab7d2d6dc9a01e3f |
| 最终状态 | completed |
| 最终柔度 | 222.34367286963868 |
| 最终体积分数 | 0.4000004507394733 |
| 体积分数绝对误差 | 约 4.51e-7 |
| 实际迭代数 | 4 |
| 灰度比例 | 0.86 |

真实收敛数组为：

    664.0349 -> 414.4385 -> 296.3832 -> 222.3437

该 run 有 result.mat、result.json、density.csv、4 个 progress snapshot、convergence.png 和 density.png。两张 PNG 均由 MATLAB 本次结果写出：收敛图使用 objective_history，密度图使用最终 density，不是前端定时器或模拟图。

结论：完整数据路径、MATLAB 可执行、运行状态、实时帧和制品导出均已验证。四次迭代使灰度比例为 0.86，因此该任务只用来验收通路，不能视作收敛或高质量拓扑设计。

## 真实取消分支

取消压力任务：

| 字段 | 实际值 |
| --- | --- |
| 网格 | 60 x 30 |
| 最大迭代 | 100 |
| Engineering run ID | eng-990afc027342412b8c7b6b02bc96fe43 |
| 取消前真实迭代数 | 51 |
| 最终状态 | cancelled |
| 事件证据 | MATLAB 工程运行已取消 |

调用 engineering run cancel 加 --confirm 后，运行状态转为 cancelled。进程检查确认没有遗留 matlab.exe。该 run 不被作为已完成 Engineering 基线，也不被标记为完成设计。

## 导出完整性

已对 completed run 执行 engineering export，输出目录为：

    D:\项目\拓扑挑战杯\_verification\exports-20260830\
      topoptpilot-eng-01d3dfebbdbf4b55ab7d2d6dc9a01e3f

导出命令对服务器清单中每一个制品逐个下载、计算 SHA-256 并比较。清单、配置、MATLAB 结果、真实图片、snapshot 与报告均已写入 export-manifest.json。

## Policy 命令闸门

完成的 Engineering run 已成功导入为 Research 基线，创建项目 MBB-002。随后：

1. research propose 先调用 research_get_context，再调用 policy_compile_intent；
2. 得到 Proposal P-C6D2A8FD39；
3. research preview 返回可提交预览；
4. 未带 --confirm 的 research submit 返回 CONFIRMATION_REQUIRED，退出码为 2；
5. 没有提交正式 Policy 实验。

该验证证明 CLI 不会以 Engineering 2D 基线冒充 Policy 正式实验，也不会因 Agent 的文本请求越过确认。

## 后续安全回归

在首轮闭环之后，继续发现并修复了三个会影响无界面 Agent 可靠性的边界问题，并重新执行真实验证：

| 项目 | 最终结果 |
| --- | --- |
| Windows Runtime 取消 | 受控子进程被加入 kill-on-close Windows Job Object；超时/取消能终止完整子进程树，受限环境不支持 Job Object 时才安全回退到 taskkill。 |
| 更新后的真实 MATLAB 完成运行 | eng-dd2d7d43692448dbbb3601604e9ae26d，20 x 10、4 迭代、completed、柔度 222.34367286963868、体积分数 0.4000004507394733。 |
| 更新后的真实 MATLAB 取消运行 | eng-f7b74855d4b14277a0b6a6ff4dd5d140，确认有真实迭代事件后取消，状态 cancelled、取消时 4 轮、无遗留 matlab.exe。 |
| 重复报告与导出 | 同名报告不再把自身旧哈希写入正文，服务端替换 report ref；重复导出时 SHA-256 校验全部通过。 |
| 中文路径机器协议 | 默认 JSON 使用 ASCII Unicode 转义；PowerShell ConvertFrom-Json 已验证能恢复导出目录并读取 manifest。 |

最终导出使用 eng-dd2d7d43692448dbbb3601604e9ae26d，导出根目录：

    D:\项目\拓扑挑战杯\_verification\exports-20260830-machine-json\
      topoptpilot-eng-dd2d7d43692448dbbb3601604e9ae26d

该导出包含 26 个经过服务端清单 SHA-256 校验的制品，含 result.mat、density.png、convergence.png、迭代 snapshot 和 export-manifest.json。

## 无界面交接与首次初始化

为了让 Codex、Pi、CI 或其他终端 Agent 在不打开桌面客户端的情况下发现并使用受限入口，增加了 scripts/bootstrap_headless.ps1，并在根 README 与 docs/topoptctl.md 增加了最短无界面路径。

该脚本的边界与实测结果如下：

| 检查 | 结果 |
| --- | --- |
| JSON 跳过安装模式 | -VenvPath .venv -SkipPythonDependencies -SkipPiRuntime -Json 返回 ok=true、status=ready，且明确声明未读写凭据、未启动 Sidecar/MATLAB/Engineering/Research。 |
| 既有 Pi 运行时 | 在不传 -ReinstallPiRuntime 的情况下，检测到 Pi CLI 后返回 piRuntime=present，不重写 node_modules。 |
| 目录边界 | 指向仓库外虚拟环境目录会返回结构化失败；脚本不会在仓库外创建环境。 |
| 重装边界 | 若已有 node_modules 但 Pi 不完整，默认拒绝覆盖；只有显式 -ReinstallPiRuntime 才允许执行锁定的 npm ci --ignore-scripts。 |
| 自动化回归 | 新增 bootstrap 契约测试 3 项；全量 Python 测试为 214 passed。 |

引导器不替代 doctor、MATLAB 配置、Qwen 配置或用户确认。首次依赖准备完成后，调用方仍须通过 topoptctl daemon start、doctor、engineering plan 和显式 --confirm 的正式命令序列完成后续操作。

## 结论与后续

topoptctl 已能承担当前验收所需的无界面入口。暂不引入 CLI-Anything 作为运行时，因为它不能替代已有的严格 Schema、确认、Sidecar 身份、凭据隔离和 artifact 哈希验证。

后续若需要正式交付，应在干净机器上重复本记录的命令、运行全量测试、重新检查 Qwen 凭据权限，并为较大迭代任务评估收敛和灰度质量；不得把此极小样例的数值用于性能或科学结论。
