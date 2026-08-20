# TopOptPilot V5.0 — Pi-native Local Research Workspace

> **V5.0 当前实现**：官方 `@earendil-works/pi-coding-agent` 以 JSON-RPC 常驻运行，
> 每个 Research ID 对应一个可恢复 Pi session。Pi 只接触 11 个科研工具；参数由确定性
> Safety Policy 编译，目标与评价来自真实 2D/3D FEM，而不是大模型猜测。

面向三维工程结构拓扑优化的**可验证假设生成与自动实验智能体**（AI Scientist）

| 字段 | 内容 |
|------|------|
| **对应赛题** | XH-202619 基于国产开源大模型的 AI Scientist 的研发与应用 |
| **技术底座** | 官方 Pi RPC + Qwen 3.7 Plus + Python 2D/3D FEM + 可选 MATLAB |
| **核心定位** | 大模型做科研推理，MATLAB/CUDA 做确定性物理计算，评价器做客观裁决 |

---

## 系统定位

TopOptPilot 不是"自然语言调一次拓扑优化"的工具。它是：

1. **论文方法工程化** — 将论文转化为带证据、适用条件、风险说明和验证状态的 MATLAB 插件（Paper-to-Plugin）
2. **三维拓扑优化自动实验** — 调用 C++/CUDA MEX 求解器完成真实仿真，根据结果反复修正方案
3. **可验证科研假设生成** — 产生被证据支持或被否定的科学假设，附带完整可复现研究报告

**核心原则**：大模型不代替有限元求解器。Pi 负责科研意图、证据解释与工具编排；
Safety Policy 负责把意图编译成合法受控实验；Python/MATLAB 负责确定性计算，Evaluator 客观裁决。

## V5.0 快速开始

```powershell
npm install
pip install -r requirements.txt
Copy-Item .env.example .env
# 在 .env 中填写 DASHSCOPE_API_KEY
python launch.py
```

模型默认使用 `qwen3.7-plus` 与 `https://dashscope.aliyuncs.com/compatible-mode/v1`。
密钥仅由 `.env` 注入，不写入 session、报告或复现包。无模型或调用失败时进入
Safe Mode，确定性规则策略仍通过同一 Policy 编译器推进实验。

V5 核心目录：`.pi/extensions/topopt-tools.ts`（11 工具沙箱）、`.pi/skills/`（六项动态技能）、
`topoptpilot/agent_runtime/`（Pi RPC/会话/网关）、`topoptpilot/memory/`（L0–L3）、
`topoptpilot/policy/`（意图与安全策略）、`solver/topopt3d.py`（Hex8 FEM）、
`topoptpilot/benchmarks/`（Random/Grid/TPE/Rule/Pi 与消融）。

---

## 四层架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      输入与知识层                                 │
│  论文PDF · 工程需求 · 体素模型 · 边界条件 · 材料 · 基线 · 历史结果 │
├──────────────────────────────────────────────────────────────────┤
│                     AI Scientist 层                               │
│  研究主管 → 证据Agent → 假设Agent → 审稿Agent                   │
│         → 实验Agent → 审计Agent（六角色协作）                    │
│  状态机：输入验证→文献挖掘→假设生成→审稿→实验→审计→迭代/终止     │
├──────────────────────────────────────────────────────────────────┤
│               方法与求解层                                        │
│  MATLAB可组合插件（OC/MMA/滤波/投影/控制器/评价器）              │
│  + CUDA MEX（Matrix-free FEM · PCG/MGCG · 单元柔度 · 灵敏度）    │
│  + 知识库（SQLite结构化 + FAISS语义检索）                         │
├──────────────────────────────────────────────────────────────────┤
│               资产与输出层                                        │
│  3D结构(STL/VTK) · 指标曲线 · 研究报告 · 独立复核 · 一键复现包   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
TopOptPilot/
├── README.md                     # 本文档
├── 架构.md                       # 完整架构文档
├── 示范案例说明.md               # 三个演示案例 + 实验矩阵
├── TopOptPilot_架构图.html        # SVG架构图(浏览器打开)
├── requirements.txt              # Python 依赖
├── .env.example                  # 环境变量模板
├── .gitignore
│
├── agent/                        # AI Scientist 核心层
│   ├── orchestrator.py           # 主编排器：科研闭环主循环
│   ├── state_machine.py          # 科研状态机（8状态+转换规则）
│   ├── prompts/system_prompts.py # 6角色系统提示词模板
│   ├── roles/                    # 6个Agent角色实现
│   └── tools/                    # 论文阅读、引用核查工具
│
├── plugins/                      # MATLAB 插件接口层
│   ├── interfaces/               # 6个MATLAB抽象基类
│   ├── registry/                 # 注册表+兼容性+生命周期
│   ├── specifications/template.yaml # 插件说明书模板
│   └── implementations/          # (空)等待具体插件开发
│
├── mcp/                          # MCP 接口桥（保留接口）
│   ├── matlab_mcp/               # MATLAB通信桥
│   └── solver_mcp/               # CUDA MEX求解器桥
│
├── knowledge/                    # 知识/证据层
│   ├── evidence_db.py            # 论文证据数据库
│   ├── method_card.py            # 方法卡片数据模型
│   └── paper_processor.py        # PDF→结构化数据
│
├── experiments/                  # 实验管理层
│   ├── task_generator.py         # task.json生成
│   ├── experiment_runner.py      # 实验执行器
│   ├── solver_runner.py          # 实验求解运行器（真实引擎调度）
│   ├── result_manager.py         # 结果管理+聚合指标
│   ├── experiment_matrix.py      # 实验矩阵(B0/B1/A1/A2/Ours/Ablation)
│   └── schemas/                  # JSON Schema
│
├── solver/                       # 求解器模块（真实拓扑优化引擎）
│   ├── topopt_engine.py          # 主优化循环统一入口 run_topopt()
│   ├── fe_solver.py              # 有限元求解（刚度矩阵/稀疏直接解/灵敏度）
│   ├── oc_solver.py              # OC 最优性准则更新
│   ├── filters.py                # 灵敏度/密度滤波 + Heaviside 投影
│   ├── continuation.py           # β/penal 延续调度与反馈控制器
│   ├── params.py                 # 任务参数规范化 → task_spec
│   ├── result_schema.py          # 结果契约（灰度/连通/ExperimentResult）
│   └── matlab_backend.py         # MATLAB Engine 后端（可选）
│
├── assets/                       # 资产与输出
│   ├── report_generator.py       # 研究报告生成
│   └── visualization.py          # 收敛曲线/指标图表
│
├── app.py                        # Streamlit 稳定入口
├── launch.py                     # 环境检查 + Workspace 启动器
├── topoptpilot/                  # V5 Workspace / Pi RPC / Policy / Memory / Solver
├── frontend/cockpit.py           # 旧 CLI（兼容保留）
├── demo/                         # 演示案例
│   ├── run_solver_demo.py        # 赛题B演示：真实引擎逐步提升实验成效
│   ├── demo_runner.py            # 10分钟演示编排
│   ├── paper_to_plugin.py        # Paper-to-Plugin流水线
│   └── sample_inputs/bracket_task.json # 3D支架任务示例
```

---

## 求解器模块（solver/）

真实拓扑优化引擎，取代 `ExperimentQueue` 的随机占位模拟（`缺口分析.md` 缺口 #3 修复）。
把原始 MATLAB 的 `FE_solver.m` + `OC_solver.m` 求解器移植为 numpy/scipy 实现，
与 MATLAB 地面真值逐点一致，并提供 MATLAB Engine 双后端。核心创新不是"一键求解"，
而是**参数驱动**：柔度 / 灰度 / 连通性随 beta、penal、滤波、控制器真实变化，
从而支撑"实验 → 审计 → 调参 → 改善"的闭环证据链。

### 包结构

| 模块 | 职责 |
|------|------|
| `fe_solver.py` | 有限元求解：单元刚度矩阵、全局组装、稀疏直接求解、单元柔度与灵敏度 |
| `oc_solver.py` | OC 最优性准则更新（二分 λ 满足体积约束） |
| `filters.py` | 灵敏度滤波 / 密度滤波 / Heaviside 投影及其链式导数、伴随灵敏度 |
| `continuation.py` | 延续调度：β 控制器（fixed/periodic/gray_feedback/joint_feedback）与 penal 延续 |
| `params.py` | 任务参数规范化：ExperimentTask / JSON → 统一 `task_spec`（网格/边界/默认值） |
| `result_schema.py` | 结果契约：`gray_ratio` / `connected_components` / ExperimentResult 兼容 dict |
| `topopt_engine.py` | 主优化循环统一入口 `run_topopt()` |
| `matlab_backend.py` | MATLAB Engine 后端：调用原始 `.m` 求解（需 `matlabengine` 包） |

### 运行一次求解

```bash
python -c "from solver.topopt_engine import run_topopt; r = run_topopt({...}); print(r['objective'])"
```

B0 无投影基线示例（60×30 MBB，volfrac=0.4）：

```bash
python -c "from solver.topopt_engine import run_topopt; \
r = run_topopt({'task_id':'B0','experiment_group':'B0','hypothesis_id':'H0',\
'load_case':'vertical','mesh_level':'medium','projection':'none',\
'controller':'fixed_controller','filter':'sensitivity_filter',\
'params':{'volfrac':0.4,'rmin':1.5,'max_iter':150},\
'work_package':{'volume_fraction':0.4}}); \
print(r['objective']); print(r['quality'])"
```

结果 `r` 为 ExperimentResult 兼容 dict：`r["objective"]["compliance"]`、
`r["quality"]["gray_ratio"]`、`r["quality"]["connected_components"]`、
`r["solver"]["relative_residual"]`、`r["artifacts"]["history"]`（含迭代级
compliance/change/volume_fraction/gray_ratio/connected/beta/penal 历史）。

### 三条物理路径

| 路径 | filter | projection | 数学结构 |
|------|--------|-----------|----------|
| A. 经典灵敏度滤波（99-line） | `sensitivity_filter` | `none` | xPhys=x；dc=check(dc, rmin, x) —— 与 MATLAB 地面真值逐点验证 |
| B. 密度滤波 SIMP（88-line 去投影） | `density_filter` | `none` | xPhys=H@x；dc_x=H@dc_xPhys |
| C. 密度滤波 + Heaviside 投影（88-line 完整） | `density_filter` | `heaviside_projection` | xTilde=H@x；xPhys=heaviside(xTilde, β)；dc_x=H@(dc_xPhys·heaviside'(xTilde)) |

### 控制器 → 实验组映射

| 控制器 | 实验组 | 含义 |
|--------|--------|------|
| `fixed_controller` | B0 | 无投影基线：β 恒 0，纯 SIMP |
| `periodic_controller` | B1 | 固定周期调度：β 按固定步长/间隔递增（无反馈） |
| `gray_feedback_controller` | A1 | 灰度反馈：灰度未达标时延迟 β 提升 |
| `joint_feedback_controller` | Ours | 联合反馈：灰度 + 连通性双反馈，步长更温和 |

### MATLAB 双后端

`backend="matlab"` 时通过 MATLAB Engine 调用原始 `.m` 文件（需先 `pip install matlabengine`）；
未安装或未配置时回退 Python（numpy/scipy）实现。统一入口不变：

```bash
python -c "from solver.topopt_engine import run_topopt; \
print(run_topopt({...}, backend='matlab')['objective'])"
```

### 与实验层的集成

`experiments/experiment_queue.py` / `experiments/solver_runner.py` 默认
`backend="python"`，把 ExperimentTask 交给 `solver.topopt_engine.run_topopt`，
得到**真实物理结果**（柔度 / 灰度 / 连通性随参数真实变化，反映"调参 → 改善"
的因果关系），替代原先的随机占位模拟。`backend="simulate"` 仍保留旧随机占位
结果，仅用于演示预计算场景。

### 验证记录

引擎经典路径与 MATLAB 经典 99-line 地面真值逐点核对：60×30 MBB、volfrac=0.5 下
iter1=391.91、iter10=148.83、iter60=127.69、iter200=111.73，
最终密度场逐元素最大偏差 ≤1.2%（由求解器移植验证脚本逐点核对）。

### 赛题 B 演示

`demo/run_solver_demo.py` 用真实引擎复现赛题 B 叙事
**"AI 根据实验结果调整下一轮计划，逐步提升实验成效"**：

```bash
python demo/run_solver_demo.py
```

Round 0 全量探索：B0 无投影基线 FAIL（灰度 0.821、断连 4）→ B1 周期调度 SUCCESS（C≈84.6）；
Round 1 审计驱动调参：盲锐化对照 C≈113.5（退化）→ 灰度反馈 A1 C≈92.0 → 联合反馈 Ours C≈81.6
（柔度最优）。柔度 239.9→81.6（↓66%）、灰度 0.821→0.013（↓98%）、连通 4→1，
全程真实求解、确定性、约 20 秒跑完。

---

## 当前状态

| 层级 | 模块 | 状态 | 说明 |
|------|------|------|------|
| Agent | 6角色+编排器+状态机+提示词 | ✅ 完成 | 39个Python文件，3,241行代码，全部语法通过 |
| Plugin | 6个MATLAB基类+Python注册表 | ✅ 接口层完成 | 实现层为空，等待人工开发 |
| MCP | MATLAB桥+CUDA桥 | ✅ 接口占位 | 具体实现依赖 pip install matlabengine |
| Knowledge | 证据库+方法卡片 | ✅ 关键词检索 | 待升级为SQLite+FAISS三级架构 |
| Solver | 真实拓扑优化引擎+双后端 | ✅ 完成 | numpy/scipy移植，与MATLAB地面真值逐点验证 |
| Experiment | 任务生成+运行器+结果管理 | ✅ 完成 | 预定义六组实验矩阵 |
| Frontend | Streamlit Workspace | ✅ V5.0 | Explorer + Pi Stream + Inspector + Baselines |
| Test API | FastAPI | ✅ V5.0 | 与 Streamlit 共用 ResearchService |
| Demo | 10分钟演示编排 | ✅ 完成 | 9阶段时间线+Paper-to-Plugin流水线 |

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DASHSCOPE_API_KEY

# 3. 启动唯一主界面
streamlit run app.py

# 或执行环境/求解器检查后启动
python launch.py

# 4. （可选）启动赛题测试 API
uvicorn topoptpilot.api.fastapi_app:app --host 127.0.0.1 --port 8000

# 5. （可选）赛题 B 演示：真实求解器逐步提升实验成效（无需 API Key）
python demo/run_solver_demo.py
```

Workspace 支持自然语言和统一命令输入：`/run`、`/pause`、`/resume`、`/stop`、
`/approve`、`/reject`、`/rollback E01`、`/compare E01 E02`、`/lock beta 8`、
`/promote E01`、`/retry E01`、`/report`、`/export`。

---

## 边界情况评估

### ✅ 已覆盖的边界

任务包字段缺失、无假设可审、预算耗尽、连续无信息增益、求解残差超标、
跨网格结论不一致、假设被明确否定、最大迭代次数、插件组合非法

### ❌ 缺失（P0 必须补）

CUDA MEX 崩溃自动重启、NaN/Inf 运行时检测、PiAgent/DeepSeek API 超时重试、
多条诊断规则同时触发的优先级裁决、两个假设结果无法区分时的区分性实验

### ❌ 缺失（P1 重要）

论文 PDF 无法解析的降级策略、证据库为空的种子植入、材料/几何数值合法性校验、
磁盘空间不足检测、参数回滚机制（RollbackManager）、插件缺失自动回退链

---

## 知识库架构规划

**当前**：JSON 文件 + 关键词匹配（跨语言检索差，无语义搜索）

**目标**：三级存储架构

```
[L1] 文件系统     → PDF/STL/MAT 原始文件
[L2] SQLite+FTS5 → 结构化元数据 + 全文索引
[L3] FAISS        → 向量嵌入 + 语义检索

+ 自进化机制：每次实验后自动写入结果和裁决，建立历史相似实验索引
+ 冲突检测：检测两篇论文对同一方法的矛盾结论
+ 种子库：首次运行时自动植入至少5篇核心论文的方法卡片
```

---

## 改进方向 🚧

### P0 — 必须（不改则系统无法可靠运行）

| # | 改进项 | 说明 | 关联问题 |
|---|--------|------|---------|
| 1 | **LLM Client + ResponseParser** | 将6个Agent从纯Python逻辑升级为LLM驱动 | Agent当前是"哑"的 |
| 2 | **实验队列异步化** | ExperimentQueue 支持异步提交+轮询+回调 | 30组GPU实验不可同步等 |
| 3 | **运行时异常处理** | CUDA崩溃自动重启、NaN检测、API重试 | 三个P0缺失边界 |

### P1 — 重要（否则闭环脆弱）

| # | 改进项 | 说明 | 关联问题 |
|---|--------|------|---------|
| 4 | **粗网格快速筛选** | 完整实验前先用粗网格筛掉无效方案 | 计算预算易被吃光 |
| 5 | **结构化输出约束** | 每个Agent追加JSON Schema输出格式 | LLM回复不可预测 |
| 6 | **参数回滚机制** | RollbackManager + 两个新状态 | 失败→修正叙事的工程基础 |
| 7 | **假设精炼 + 区分性实验** | 三个缺失状态（见架构.md §2） | 纠偏路径不完整 |
| 8 | **插件缺失回退链** | 自动查询FallbackChain选择替代插件 | 无插件的降级策略 |

### P2 — 加分（提升质量与演示效果）

| # | 改进项 | 说明 |
|---|--------|------|
| 9 | **事件驱动状态机** | 支持条件跳转注册，灵活响应异常 |
| 10 | **三级知识库升级** | SQLite+FTS5 + FAISS |
| 11 | **假设模糊度检测器** | 自动识别不可证伪的假设表述 |
| 12 | **知识冲突检测** | 发现两篇论文对同一方法的矛盾结论 |

---

## 十分钟演示时间线

| 时间 | 内容 | 核心信息 |
|------|------|----------|
| 0:00–0:50 | 问题与差距 | 方法多选择难，三维实验成本高 |
| 0:50–1:40 | 系统架构 | PiAgent/DeepSeek决策→MATLAB方法→CUDA物理 |
| 1:40–2:40 | 上传论文与任务 | 真实PDF+支架边界条件 |
| 2:40–3:40 | Paper-to-Plugin | 公式/页码/条件→方法卡片 |
| 3:40–4:40 | 候选假设竞争 | 3项候选+审稿Agent反例 |
| 4:40–6:10 | 真实求解 | GPU运行+残差曲线实时更新 |
| **6:10–7:20** | **失败与修正** | **一轮断连→Agent回滚→调整控制器** |
| 7:20–8:30 | 第二轮与对比 | 结构/灰度/柔度/时间对比表 |
| 8:30–9:20 | 独立复核 | 重建网格+独立FEM云图 |
| 9:20–10:00 | 研究报告 | 假设等级+适用边界+复现包 |

---

## 赛题字段映射

| 赛题字段 | TopOptPilot 自动生成 |
|----------|---------------------|
| Problem Statement | 当前方法局限、适用场景与可证伪问题 |
| Rationale | 论文证据、知识缺口、候选解释和推导链 |
| Technical Details | PiAgent、DeepSeek、插件、FEM、CUDA、优化器、指标 |
| Datasets — Source | 论文配置、基线实验和已有场数据 |
| Datasets — Target | 待运行的密度、位移、柔度、残差数据 |
| Paper Title/Abstract | 仅在真实结果完成后生成，禁止预写正向结论 |
| Methods | 数学模型、插件组合、自适应规则与求解流程 |
| Experiments | 基线、消融、跨网格、多载荷、GPU/GPU一致性 |
| Results | 真实运行数值、曲线、统计和否定结果 |
| References | 经过DOI/URL与原文位置核验的论文 |

---

## 许可证

项目基于 TOP3D_XL (BSD-2-Clause) 扩展开发。参赛材料中的参数、载荷工况、实验数据和性能数据必须替换为团队实际运行与核验后的版本。

---

> **项目以赛题评审视角组织，核心创新不在一键求解，而在 Paper-to-Plugin + 可信工具闭环 + 可证伪假设竞争 + 全链路可复现。**
