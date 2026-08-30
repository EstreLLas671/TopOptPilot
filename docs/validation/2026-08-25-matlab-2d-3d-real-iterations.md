# TopOptPilot：用户 2D/3D MATLAB 源码与真实迭代可视化验收

日期：2026-08-25

## 源码边界

- 2D 来源：F:\Other\揭榜挂帅\code\拓扑优化\TopOpt_2D
- 3D 来源：F:\Other\揭榜挂帅\code\拓扑优化\TopOpt-3D
- 安装包副本：matlab/engineering/TopOpt_2D 与 matlab/engineering/TopOpt-3D
- 3D 的 14 个 MATLAB 文件按字节与用户源码一致。
- 2D 除 topopt_main.m 外均按字节一致；topopt_main.m 只增加 iteration_callback，回调发生在每轮真实 FE、灵敏度滤波和 OC 更新之后，不修改求解方程、边界条件或密度更新。
- 文件级来源哈希记录在 matlab/engineering/solver-sources.json，该清单随安装包提供。

## 调度规则

- 参数配置必须明确选择“二维 2D”或“三维 3D”。
- 2D 调用 TopOpt_2D/topopt_main.m，运行请求固定 nelz=1。
- 3D 调用 TopOpt-3D/topopt3d_main.m，保留用户配置的 nelz。
- 本机 MATLAB 失败时任务失败，不回退到 Python，也不生成模拟结果。
- provenance 写入 solverDimension 和 solverEntry。

## 真实迭代数据流

每轮 MATLAB 回调依次执行：

1. 将真实密度场写入 snapshots/iter_NNNN_density.bin。
2. 3D 开启逐轮应力时写入 snapshots/iter_NNNN_von_mises.bin。
3. 原子更新 snapshots/manifest.json。
4. sidecar 验证文件位于本次 run 目录并计算 SHA-256。
5. progress 事件携带路径、shape、维度和摘要。
6. “迭代可视化”读取 float32 little-endian、MATLAB F-order 制品后渲染；无真实帧时只显示等待状态。

## MATLAB R2024b 实测

MATLAB：D:\Tools\matlab\MATLAB R2024b(64bit)\bin\matlab.exe

### 2D

- 网格：8×4
- 迭代：3
- 柔度：614.5700 → 448.3969 → 381.6842
- 密度帧：3
- 清单 shape：[4,8]
- solver entry：TopOpt_2D/topopt_main.m

### 3D

- 网格：8×4×3
- 迭代：3
- 每轮均生成真实密度和 Von Mises 应力帧
- 清单 shape：[4,8,3]
- solver entry：TopOpt-3D/topopt3d_main.m

### 完整 RunManager 验收

- run：eng-cc910a68885b4bcc958a965e1a5a41db
- 状态：completed
- progress 事件：2
- 第 1 轮密度 SHA-256：cfcfa58e63473926e6f1f2914aa2168a6aff6198f2a500752f7e5c12118fcd1a
- 第 2 轮密度 SHA-256：50e3919adb6603733f38f6a41bd3aa4343e94742326f18ac4e130793acc7b1c3
- provenance：local-matlab / 2d / TopOpt_2D/topopt_main.m

## 自动化验证

- Python：170 passed
- Vitest：63 passed
- Rust：32 passed
- React production build：通过
- Python compileall：通过
- Rust fmt：通过
- git diff --check：通过
## 标准安装包

- 文件：TopOptPilot_2.0.0_x64-setup.exe
- 大小：188928067 bytes（180.18 MiB）
- SHA-256：BE4D22AA3731B87F82742E05F6D1A4B6925ADACAE39C9CD2C270936815D959C5
- 签名：NotSigned
- 打包 sidecar：健康检查 200；带令牌设置接口 200；无令牌设置接口 401
- 标准包包含 Node、MCP、.pi、sidecar 和 2D/3D MATLAB 源码，不包含 MATLAB Runtime DLL 或编译 Runtime solver。
