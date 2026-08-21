import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export const resources = {
  "zh-CN": { translation: {
    appName: "TopOptPilot", newResearch: "新建研究", research: "研究", experiments: "实验",
    evidence: "证据", decisions: "决策", files: "文件", researchStream: "研究流",
    inspector: "检查器", noResearch: "创建或选择一个研究项目", goal: "研究目标",
    constraints: "约束条件", budget: "预算", currentRun: "当前实验", parameters: "参数",
    metrics: "指标", compliance: "柔度", gray: "灰度率", components: "连通分量",
    progress: "进度", topology: "拓扑", convergence: "收敛历史", approve: "批准",
    edit: "编辑", reject: "拒绝", why: "为什么", send: "发送", commandPlaceholder: "询问 TopOptPilot 或输入命令…",
    autonomous: "开始自主研究", matlab: "MATLAB MCP", restart: "重启", connected: "已连接",
    available: "可用", unavailable: "不可用", ready: "就绪", language: "English",
    name: "名称", create: "创建", cancel: "取消", objective: "优化目标", locale: "语言",
    status: "状态", backend: "后端", model: "模型", refresh: "刷新", report: "生成报告",
    export: "导出复现包", compare: "比较", loading: "正在连接本地科研服务…",
    serviceError: "无法连接桌面后端", noEvents: "尚无研究事件", humanApproval: "需要人工审批",
    save: "保存", close: "关闭", matlabStrict: "F3 仅接受真实 MATLAB MCP 结果",
    createHint: "输入结构目标与预算，数值参数仍由 Policy 编译。"
  }},
  "en-US": { translation: {
    appName: "TopOptPilot", newResearch: "New research", research: "Research", experiments: "Experiments",
    evidence: "Evidence", decisions: "Decisions", files: "Files", researchStream: "Research stream",
    inspector: "Inspector", noResearch: "Create or select a research project", goal: "Research goal",
    constraints: "Constraints", budget: "Budget", currentRun: "Current experiment", parameters: "Parameters",
    metrics: "Metrics", compliance: "Compliance", gray: "Gray ratio", components: "Components",
    progress: "Progress", topology: "Topology", convergence: "Convergence history", approve: "Approve",
    edit: "Edit", reject: "Reject", why: "Why", send: "Send", commandPlaceholder: "Ask TopOptPilot or enter a command…",
    autonomous: "Start autonomous research", matlab: "MATLAB MCP", restart: "Restart", connected: "Connected",
    available: "Available", unavailable: "Unavailable", ready: "Ready", language: "中文",
    name: "Name", create: "Create", cancel: "Cancel", objective: "Objective", locale: "Language",
    status: "Status", backend: "Backend", model: "Model", refresh: "Refresh", report: "Generate report",
    export: "Export reproduction bundle", compare: "Compare", loading: "Connecting to the local research service…",
    serviceError: "Unable to connect to the desktop backend", noEvents: "No research events yet", humanApproval: "Human approval required",
    save: "Save", close: "Close", matlabStrict: "F3 accepts only genuine MATLAB MCP results",
    createHint: "Enter the structural goal and budget; Policy still compiles all numeric parameters."
  }}
} as const;

const stored = localStorage.getItem("topoptpilot.locale");
i18n.use(initReactI18next).init({
  resources, lng: stored === "en-US" ? "en-US" : "zh-CN", fallbackLng: "zh-CN",
  interpolation: { escapeValue: false }
});

export default i18n;
