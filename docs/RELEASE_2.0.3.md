# TopOptPilot 2.0.3 发布说明

发布日期：2026-08-30

TopOptPilot 2.0.3 集中修复 Research 与工程历史会话的切换竞态、工程结果长期加载和科研最终方案误弹窗，并新增真实 Von Mises 应力评估与专业中文黑白科研报告。

## 主要更新

### Research 与历史对话性能

- Research 选择立即生效，旧详情请求不能覆盖最后一次选择。
- 切换 Research 时清理上一实验选择，WebSocket 增量合并并节流完整对账。
- 新建、删除、归档和恢复采用行级忙碌状态，不锁住整个列表。
- 工程历史会话由单一控制器管理，切换不重复拉取会话列表。
- 修复父子会话列表的空数组状态回写循环，改善切换、新建和删除卡顿。
- 工程与科研聊天草稿继续按项目、会话和 Research 隔离。

### 最终方案与界面一致性

- 删除进入或切换 Research 时自动弹出最终方案的行为。
- 最终方案只能通过“查看最终方案”显式打开；没有真实最佳实验时按钮禁用。
- 工程开发与 AI 科研共用固定顶栏高度，模式切换不再发生几何跳变。

### 工程结果读取

- 每个结果版本只读取一次 manifest，并行读取 density、stress 和 history。
- 使用 `runId + manifest SHA-256` 缓存解析结果，取消旧运行读取。
- WebSocket 作为运行事件主通道，轮询仅作低频单飞兜底。
- 运行进入终态后立即回放已持久化迭代事件，再进行有限次数最终制品索引对账。
- 超过对账上限时显示明确失败和重试状态，不再无限显示“加载中”。

### 真实应力评估

- Python 2D Q4 与 3D Hex8 基于最终位移场计算单元 Von Mises 应力。
- MATLAB MCP 校验并持久化真实 `von_mises`，验证 shape、有限值、F-order 和哈希。
- 结果记录最大 Von Mises 应力、单位、单位可信度、应力制品和证据 ID。
- 只有几何、载荷、材料和求解器单位链可信时以 MPa 展示并执行许用应力判断。
- 单位链不完整时显示归一化最大应力；应力计算失败时保留其他真实指标并说明原因。

### 专业科研报告

- 新增受控报告模板，使用专业中文字段与确定性 Research State 数据。
- 默认生成 `<报告名>.md`、`<报告名>.pdf` 和 `<报告名>_assets/`。
- 三维实验使用真实三维密度生成固定视角表面图，不以二维投影冒充三维结果。
- 报告可包含真实三维拓扑、应力分布和柔度收敛曲线。
- Markdown 使用相对资源路径，PDF 内嵌相同图像。
- 全文采用黑、白、灰配色；缺失内容明确写为“未提供”或“未计算”。
- 先在临时目录生成全部文件，再原子移动到目标目录；覆盖同名报告必须明确确认。
- 导出成功后显示路径、大小和 SHA-256。

### 数据隔离

- Python 测试启动前强制使用独立临时数据目录，不写入正式 LocalAppData。
- 安装包和源码仓库不包含用户 Research、会话、审批记录、日志、数据库或测试数据。
- 发布前对开发机旧 Research 数据执行了用户授权的一次性备份与清理；该维护操作不是产品升级逻辑。

## 使用提示

1. 安装或升级后，在“设置 → Agent 与模型”中确认默认模型和连接状态。
2. 使用 MATLAB 后端时，在工程右栏确认 MATLAB 探测通过。
3. 完成工程运行后，在“结果”中核对密度、真实应力、单位可信度和制品哈希。
4. 保存工程方案后，可在 AI 科研 Composer 左侧“+”中导入作为 Research 基线。
5. 自主研究结果完成后，点击左侧“查看最终方案”；切换 Research 不会自动弹窗。
6. 导出科研报告时输入报告名称和目录，默认同时生成 Markdown、PDF 和图像资源。

完整操作流程见仓库根目录 [README.md](../README.md)。

## 安装包边界

目标安装包：`TopOptPilot_2.0.3_x64-setup.exe`。

安装包包含桌面端、Python sidecar、Agent、Node、Pi、MCP、MATLAB 2D/3D 求解器和案例资源；不包含 MATLAB 本体、MATLAB Runtime、`matlab/dist`、用户数据、API Key、测试 Research、审批记录或日志。

## 验证

- Vitest 全量测试：106 项通过。
- Python 全量测试：197 项通过。
- Rust 全量测试：34 项通过。
- 真实应力、科研报告、Research 制品与执行安全测试：通过。
- React production build：通过。
- Python `compileall`：通过。
- Rust `cargo fmt --check`：通过。
- `git diff --check`：通过。
- 科研 PDF 逐页渲染验收：通过，无乱码、缺图、截断、跨页图注错位和彩色残留。

## 正式安装包

- 文件名：`TopOptPilot_2.0.3_x64-setup.exe`
- 本地路径：`F:\\Other\\揭榜挂帅\\TopOptPilot\\.worktrees\\remote-pr\\desktop\\src-tauri\\target\\release\\bundle\\nsis\\TopOptPilot_2.0.3_x64-setup.exe`
- 文件大小：190,667,283 字节（181.83 MiB）
- 构建时间：2026-08-30 10:45:03（Asia/Shanghai）
- SHA-256：`FACB9960511C51670EE0CB9D6AFA767AF98A294E05EFD3B57ACF48CDA293F501`
- Authenticode 状态：未签名（`NotSigned`）
- 包类型：标准本机 MATLAB 版；包含完整 Agent 运行组件，不内置 MATLAB Runtime。
