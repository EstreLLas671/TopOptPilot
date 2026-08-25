# iDeskTop v2 紧凑布局、工程聊天与参数配置状态

日期：2026-08-24

## 本轮已完成

- 默认启动保持“工程开发”，中栏默认标签改为“聊天”。
- 左栏折叠后保留 48px 图标轨；研究、项目文件、补丁审批入口仍可见，点击入口会恢复左栏。
- 左栏隐藏键移到标题左侧独立区域，“新建或打开研究项目”保留在标题右侧操作区，避免重叠。
- 右栏与下栏显隐控制统一移到中栏右上角；下栏新布局默认隐藏。
- 工程运行、MATLAB 终端和运行中的科研实验通过唯一任务信号自动显示下栏；同一任务中手动关闭后不重复强制打开。
- 面板间改为中性 1px 边界和白色/极浅灰背景，小窗口保留左侧图标轨。
- 参数区更名为“参数配置”，提供四种内置工况、精度、X/Y/Z 单元、体积分数、最大迭代，以及详细参数中的 penal、rmin、最小迭代、滤波策略、求解链路、停止条件、配置 SHA-256 和恢复默认。
- Python FEM、本机 MATLAB 和编译 Runtime 共用完整任务配置；MATLAB 配置生成器保留 accuracy、filter_strategy 和 min_iterations；Python FEM 保留 penal、min_iter、filter_strategy 与 accuracy，并执行最小迭代停止约束。
- 新增只读工程聊天接口 `POST /api/engineering/assistant/chat`。未配置密钥返回 `not_configured`，在线失败返回 `safe_mode`；不产生直接写文件动作，源码只有在显式同意后才发送。
- 参数或求解链路变化后旧结果自动失效，运行期间参数与链路控件锁定。
- 顶部工作区补充边界说明：工程开发负责文件、参数、求解、结果；AI 科研负责 Research State、审批与可复现实验。

## 已通过门禁

- Python：161 项测试通过。
- 前端：58 项 Vitest 通过。
- React 生产构建通过。
- Rust：32 项测试通过，`cargo fmt --check` 通过。
- Python `compileall` 与 `git diff --check` 通过。

## 尚待真实环境验收

- 内置浏览器与 Windows 应用控制均因本机 `windows sandbox failed: helper_unknown_error: setup refresh had errors` 无法建立视觉控制连接，因此本轮没有把实际窗口截图检查标记为通过。
- 仍需在真实 Tauri 窗口中核对 100%/125% 缩放和窄窗口下的按钮位置、文本截断与抽屉滚动。
- 仍需在本机 MATLAB 上执行 12×6 小网格任务，核对真实迭代帧、密度/应力快照、报告和制品哈希；本轮没有运行 MATLAB 求解。
- 当前改动未 commit、未 push，也未更新现有 PR。