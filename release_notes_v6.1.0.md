## 🎯 V6.1.0 — 知识驱动的拓扑优化科研智能体

### ✨ 核心升级

#### 🔐 Qwen API Key 安全管理
- 设置中心支持 OpenAI-compatible 配置（API Key + 模型 ID + Base URL）
- **密钥保存到 Windows Credential Manager**，不进入 SQLite/日志/报告
- 支持连接测试，状态显示：`CONFIGURED ≠ VERIFIED`

#### 🧭 AI 引导式 Research Setup
- 6 步向导：自然语言描述 → 结构维度 → 材料单位 → 载荷约束 → 目标预算 → 合同确认
- AI 解析自然语言为结构化草案，字段标记来源（USER/DEFAULT/AI_SUGGESTED/LOCKED）
- 支持术语解释和工程模板推荐

#### 🔬 MATLAB 全保真度求解
- **F0/F1 = MATLAB 2D**（coarse/fine），**F2/F3 = MATLAB 3D**（coarse/fine）
- 所有正式实验经 MATLAB MCP，Python 求解器退出正式执行路径
- F0–F2 可自动运行，仅 F3 强制人工审批
- 新增加速变体（预计算/向量化/可选 MEX/GPU）

#### 🤖 Subagent 多角色审查
- 常驻 **Pi Research Lead** + 6 个 Subagent（Guide/Hypothesis/Planner/Executor/Reviewer/Report Writer）
- 各自独立工具白名单，权限隔离
- 歧义失败/保真度升级/最终结论必须触发 Independent Reviewer

#### 📚 离线知识库 + Knowledge Center
- SQLite FTS5 全文检索 + 模板案例 + 种子知识数据（中英双语）
- 10 份知识文档：topopt-foundations / solver-parameters / failure-patterns /
  engineering-templates / controlled-comparisons / matlab-mcp-safety / reporting-rules
- 用户可在 Knowledge Center 查看，Agent 在规划前检索

#### 📄 模板报告
- 每轮生成 Markdown 阶段报告（round-XXXX.md）
- 研究终止时生成 Markdown + PDF（六章结构）
- 数据全部来自 Research State，缺失字段不编造

### 🏗️ 架构更新

**科研状态机**（11 状态）：
SETUP → HYPOTHESIZE → PLAN → REVIEW → SUBMIT → RUN → EVALUATE → ANALYZE → COMPARE → DECIDE → REPORT

**7 种科学意图**：
ESTABLISH_BASELINE / EXPLORE_PARAMETER / REDUCE_GRAYNESS / RESTORE_CONNECTIVITY /
TEST_COMPETING_EXPLANATIONS / UPGRADE_FIDELITY / VERIFY_CANDIDATE

**16 个 Pi 工具**（新增 5 个）：
knowledge_search / knowledge_get / solver_get_capabilities / subagent_dispatch / subagent_status

### 📦 新增模块

- `topoptpilot/knowledge/` — 离线知识库（SQLite FTS5）
- `topoptpilot/reports/` — 模板报告生成器
- `topoptpilot/security/` — Windows Credential Manager 凭据管理
- `topoptpilot/agent_runtime/subagents.py` — Subagent 编排器
- `mcp/matlab_mcp/gateway.py` — MATLAB 网关增强
- `desktop/src/KnowledgeCenter.tsx` — 知识库界面
- `desktop/src/ExperimentCanvas.tsx` — 实验画布
- `desktop/src/HealthBar.tsx` — 健康状态栏（7 后端）
- `desktop/src/ResearchSetup.tsx` — 研究设置向导

### 🔌 新增 API

- `GET /api/knowledge/search` — 知识库搜索
- `GET /api/knowledge/{id}` — 知识详情
- `POST /api/settings/agent-key` — 保存 API Key
- `DELETE /api/settings/agent-key` — 删除 API Key
- `POST /api/guide` — AI 引导预览
- `POST /api/research/{id}/guide` — 应用引导建议
- `GET /api/research/{id}/agent-tasks` — Subagent 任务列表

### 📡 新增 WebSocket 事件

SUBAGENT_STARTED / SUBAGENT_RESULT / HYPOTHESIS_CREATED / REVIEW_VERDICT /
KNOWLEDGE_REFERENCED / SOLVER_CAPABILITY / SOLVER_WARMUP / SOLVER_VARIANT_SELECTED /
COMPARISON_RESULT / REPORT_READY

### 📋 发布门禁（新增 8 项）

- `credential_manager` — API Key 安全存储
- `guided_setup` — AI 引导向导
- `matlab_all_fidelity` — F0–F3 全 MATLAB
- `subagent_isolation` — Subagent 权限隔离
- `knowledge_offline` — 离线知识库
- `round_report` — 阶段报告
- `final_report_pdf` — 最终 PDF 报告
- `human_approval_f3_only` — 仅 F3 强制审批

### 📦 安装包

- **TopOptPilot_6.1.0_x64-setup.exe** (~220 MB) — NSIS 安装包
- **topoptpilot-desktop.exe** (~8.6 MB) — 独立可执行文件

### 📚 文档同步

- ✅ 产品方案.md（V6.1 完整产品计划，14 章）
- ✅ 架构.md（Subagent 架构 + 科研状态机 + 知识库 + 报告系统）
- ✅ 前端方案.md（GuidedSetup + KnowledgeCenter + SubagentPanel + RoundReport）
- ✅ 实施计划.md（V6.1 新增模块 + 4 阶段实施路线）
- ✅ 缺口分析.md（7 个 V6.1 待实施缺口 + 8 项新增门禁）

### 🔄 兼容性

- 旧 Research、旧 Python 结果和旧报告保持可读，不改写 provenance
- 仅新建 Research 使用 MATLAB-only 四级保真度
- Windows 10/11 x64，MATLAB R2024a 为签署环境
