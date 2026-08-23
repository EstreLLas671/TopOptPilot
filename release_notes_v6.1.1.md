## 🎯 V6.1.1 — 方案对齐与发布门禁补齐

> V6.1.1 在 V6.1.0 基础上补齐产品方案与代码的最后偏差：求解变体等价性验证、MATLAB 启动预热、
> MCP 启动/求解耗时统计、API 命名对齐、PDF 中文字体显式回退，以及可配置可迁移的缓存目录。

### ✨ 新增功能

#### 🔄 缓存目录可配置 + 迁移
- 设置中心 → 数据与诊断 新增「缓存目录（保存时迁移）」
- 保存时立即迁移现有缓存文件，失败自动回滚；留空则迁回默认位置
- 诊断面板显示当前缓存目录与大小；清理只清可再生缓存，不触碰 Research 记录与 MATLAB 证据
- 新增 `tests/test_cache_location.py`（7 个用例：迁移/回滚/非法目录拒绝/重启持久化/往返迁移/清理隔离）

#### 🧪 求解变体等价性验证（`matlab_equivalence` 门禁）
- `topoptpilot/benchmarks/equivalence.py`：同一受控任务下 `reference_cpu` 与 `optimized_cpu`
  compliance、密度场、迭代次数完全一致，且同标签可重复运行
- 该门禁守护「变体标签切换不改变求解行为」的不变式，纳入发布门禁

#### 🔥 MATLAB 启动预热 + SOLVER_WARMUP
- `MatlabMcpWorker.warmup()`：冷启动 MCP 进程与 MATLAB 会话并执行能力探测，首个实验不再承担启动延迟
- 重启/探测 MATLAB 后自动预热；`SOLVER_WARMUP` 事件携带预热耗时

#### ⏱️ MCP 启动/求解耗时统计
- 健康检查与诊断新增：`startup_ms`（MCP 进程启动）、`warmup`（冷启动+探测）、`last_runs`（每次求解调度耗时）
- 满足方案 12.6「记录冷启动/热启动/MCP 调度时间」的验收要求

### 🔧 对齐与修正

- **API 命名对齐**：新增 `PUT/DELETE /api/settings/agent-credential`（兼容 `agent-key`）、
  `POST /api/research/guide/parse`（与 `/api/guide` 行为一致）
- **PDF 中文字体显式回退**：Microsoft YaHei → PingFang SC → Noto Sans CJK SC → WenQuanYi Micro Hei → sans-serif
- **版本号统一为 6.1.1**：桌面端、后端 sidecar、诊断包、发布门禁
- 产品方案.md / 缺口分析.md / README.md 与实现同步（7 项 V6.1 缺口标记为已落地）

### 📦 安装包

- **TopOptPilot_6.1.1_x64-setup.exe** (~220 MB) — NSIS 安装包
- **topoptpilot-desktop.exe** — 独立可执行文件

### 🔄 兼容性

- 旧 Research、旧 Python 结果和旧报告保持可读，不改写 provenance
- 缓存目录设置向后兼容：未配置时仍使用 `<data_dir>/cache`
- Windows 10/11 x64，MATLAB R2024a 为签署环境
