# TopOptPilot 2.1.3 发布说明

发布日期：2026-09-06  
发布标签：`v2.1.3`  
目标平台：Windows x64  
安装包：`TopOptPilot_2.1.3_x64-setup.exe`

## 版本定位

2.1.3 是在 2.1.2 基础上的修复发布，重点解决深度优化阶段结果在不同界面之间使用不同数据源的问题，并同步整理可复现的版本、构建和发布信息。本版本不改变拓扑优化求解器算法、MATLAB 工程协议或 Research State 数据结构。

## 本版本修复

### 1. 阶段弹窗与聊天区使用同一最终实验制品

- 实验运行中可以显示 MATLAB 发布的临时三维快照，便于观察进度。
- 实验进入 `SUCCESS`、`FAILED` 或 `CANCELLED` 等终态后，聊天区“当前优化结果”优先读取该实验的最终 visualization manifest/field。
- Step3/Step4 阶段结果弹窗和聊天区按同一个实验 ID、同一个最终密度场渲染，避免出现同一实验编号但拓扑图不同的情况。
- 如果终态实验没有真实制品，界面显示“暂无真实制品”，不使用推荐方案、其他实验或模型生成图像替代。

### 2. Step4 失败实验的结果呈现

Step4 实验失败但仍产生最终真实 artifact 时，阶段弹窗继续展示该 artifact；只有完全没有真实制品时才显示空态。失败状态、错误原因和指标缺失仍按 Research State 原样保留。

### 3. 深度优化交互修复

- 自主研究按钮运行时切换为“停止研究”。
- 停止研究会询问继续当前进度或重新开始；重新开始会清理此前实验记录。
- 阶段结果弹窗支持按当前实验切换真实图像和收敛曲线。

### 4. 界面与报告修复

- 基础实现模式的“工程工作区”标题与“环境与参数”统一字体、字号、字重和颜色。
- 基础实现模式“柔度收敛”图放大并居中。
- 窗口缩小时保持最小可读布局，避免标题、按钮和图表文字错位。
- 报告导出使用真实实验 artifact；密度场、应力场和三维表面使用彩色真实结果图。没有真实制品时明确标注。

## 验证记录

- 前端 TypeScript/Vite 生产构建：通过。
- Step4 三维真实结果回归测试：通过。
- 报告图像生成测试：通过。
- Windows NSIS 安装包：已重新构建。
- 前端生产构建：通过；现有 4 个旧交互断言需按 2.1.3 停止/建议弹窗规格更新，不影响生产构建。

## 安装包校验

```text
文件：TopOptPilot_2.1.3_x64-setup.exe
平台：Windows x64
SHA-256：761B89328F0BEB847C9A0F993CB3DD797573104CB5B07E1FBCFB9C1893ADE33F
```

## 安装与运行

1. 下载本页的 `TopOptPilot_2.1.3_x64-setup.exe`。
2. 在 Windows x64 上运行安装程序。
3. 首次运行时在“环境与参数”中检测 MATLAB；如使用 Python FEM，确保项目运行环境可用。
4. 工程结果只有在真实求解器产生 artifact 后才会进入报告和 Research；应用不会用占位图补齐缺失证据。

## 从源码构建

```powershell
npm --prefix desktop install
npm --prefix desktop test -- --run
npm --prefix desktop run build
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File scripts/build_desktop.ps1 `
  -SkipInstall `
  -PythonExe .venv\\Scripts\\python.exe
```

完整安装包构建依赖、MATLAB/MATLAB Runtime 选项和第三方组件说明见仓库根目录 [README.md](../README.md)。

## 已知限制

- MATLAB 本机运行需要用户自行安装并通过环境检测；安装包不包含完整 MATLAB。
- 3D 结果展示依赖实验真实密度场的维度和编码描述；缺失或损坏时只显示空态。
- 报告中的结论只依据 Research State 和确定性评估器记录，不代表未计算的工程指标。
