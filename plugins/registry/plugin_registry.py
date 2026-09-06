"""
插件注册表 (Plugin Registry)

管理所有可信插件的注册、查询、兼容性验证和生命周期。

参照方案 §5.1 最小可信插件集 + §5.3 插件说明书 + §5.4 合法组合。
"""

from dataclasses import dataclass, field
from typing import Optional
import yaml
import json


@dataclass
class PluginSpec:
    """完整插件说明书（参照方案 §5.3 必填字段）"""
    # 身份
    id: str                  # 唯一ID，如 'projection.heaviside.v1'
    name: str                # 显示名称
    version: str             # 语义化版本
    type: str                # solver/filter/projection/optimizer/controller/evaluator
    language: str = "MATLAB"
    entry: str = ""          # MATLAB入口函数

    # 能力
    supported_objectives: list = field(default_factory=list)
    supported_constraints: list = field(default_factory=list)
    dimensions: list = field(default_factory=lambda: [2, 3])
    supported_solvers: list = field(default_factory=list)
    supported_optimizers: list = field(default_factory=list)

    # 参数
    parameters: list = field(default_factory=list)  # [{name, meaning, type, range, default, suggested, unit}]

    # 兼容性
    dependencies: list = field(default_factory=list)
    mutual_exclusion: list = field(default_factory=list)
    requires_chain_gradient: bool = False

    # 风险
    known_failure_modes: list = field(default_factory=list)
    applicable_boundary: str = ""

    # 证据
    paper_doi: str = ""
    paper_pages: list = field(default_factory=list)
    paper_figures: list = field(default_factory=list)

    # 验证状态
    status: str = "candidate"  # candidate / experimental / verified / deprecated
    verification_tests: dict = field(default_factory=lambda: {
        "unit_test": False,
        "finite_difference": False,
        "benchmark_mbb": False,
        "benchmark_3d": False,
        "cpu_gpu_consistency": False
    })
    verified_by: str = ""
    implementation_commit: str = ""


class PluginRegistry:
    """插件注册表"""

    def __init__(self, spec_dir: str = None):
        self._plugins: dict[str, PluginSpec] = {}
        self.spec_dir = spec_dir

    def register(self, spec: PluginSpec) -> bool:
        """注册一个插件"""
        if spec.id in self._plugins:
            existing = self._plugins[spec.id]
            if existing.version >= spec.version:
                return False
        self._plugins[spec.id] = spec
        return True

    def get_plugin(self, plugin_id: str) -> Optional[PluginSpec]:
        return self._plugins.get(plugin_id)

    def query(self, plugin_type: str = None, status: str = None,
              constraints: int = 1, dimensions: int = 3) -> list[PluginSpec]:
        """按条件查询插件"""
        results = []
        for spec in self._plugins.values():
            if plugin_type and spec.type != plugin_type:
                continue
            if status and spec.status != status:
                continue
            if constraints > 1 and not spec.supported_optimizers:
                continue
            if dimensions not in spec.dimensions:
                continue
            results.append(spec)
        return results

    def validate_combination(self, combo: dict) -> dict:
        """
        验证插件组合合法性（参照方案 §5.4）

        组合规则:
        - OC + 体积分数 + PDE滤波 = 允许（单约束基线）
        - OC + 多约束 = 禁止
        - MMA + 位移约束 = 条件允许（需梯度检查）
        - Heaviside + 无链式导数 = 禁止
        - Experimental插件 + 正式结论 = 禁止
        """
        checks = []

        solver = combo.get("solver")
        optimizer = combo.get("optimizer")
        filter_ = combo.get("filter")
        projection = combo.get("projection")
        controller = combo.get("controller")

        # 1) OC + 多约束
        if optimizer and "OC" in optimizer:
            if combo.get("constraint_count", 1) > 1:
                checks.append(("OC_multi_constraint", False,
                               "当前OC接口不支持多约束"))

        # 2) Heaviside + 无链式导数
        proj_spec = self._plugins.get(projection) if projection else None
        if proj_spec and "heaviside" in proj_spec.id.lower():
            if not proj_spec.requires_chain_gradient:
                checks.append(("Heaviside_no_gradient", False,
                               "Heaviside投影必须返回链式导数"))

        # 3) Experimental状态禁止用于正式结论
        for key in ["solver", "optimizer", "filter", "projection", "controller"]:
            pid = combo.get(key)
            if pid:
                spec = self._plugins.get(pid)
                if spec and spec.status == "experimental":
                    checks.append((f"{pid}_experimental", False,
                                   f"{pid}为Experimental状态，禁止用于正式结论"))

        # 4) 互斥检查
        for key, pid in combo.items():
            if pid and pid in self._plugins:
                spec = self._plugins[pid]
                for excl in spec.mutual_exclusion:
                    if excl in combo.values():
                        checks.append((f"{pid}_excludes_{excl}", False,
                                       f"{pid}与{excl}互斥"))

        all_valid = all(c[1] for c in checks)
        return {
            "valid": all_valid,
            "checks": [{"rule": c[0], "passed": c[1], "message": c[2]} for c in checks]
        }

    def list_by_status(self, status: str) -> list[PluginSpec]:
        return [p for p in self._plugins.values() if p.status == status]

    def get_verified(self) -> list[PluginSpec]:
        return self.list_by_status("verified")

    def get_statistics(self) -> dict:
        statuses = {}
        types = {}
        for p in self._plugins.values():
            statuses[p.status] = statuses.get(p.status, 0) + 1
            types[p.type] = types.get(p.type, 0) + 1
        return {
            "total": len(self._plugins),
            "by_status": statuses,
            "by_type": types
        }

    def load_from_directory(self, spec_dir: str):
        """从YAML规格文件批量加载插件（显式 UTF-8 解码，兼容 GBK 系统）。

        解析模板/规格的完整结构：
            plugin.*          身份与状态
            compatibility.*   兼容性、维度、链式导数要求
            parameters.*      参数规格（name/meaning/range/default/...）
            limitations.*     已知失败模式
            evidence.*        论文证据
            verification.*    验证测试开关 + 批准人
        """
        from pathlib import Path
        spec_dir = Path(spec_dir)
        for yaml_file in sorted(spec_dir.glob("*.yaml")):
            if yaml_file.name == "template.yaml":
                continue
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not data or "plugin" not in data:
                continue
            p = data["plugin"]
            if not p.get("id"):
                continue

            spec = PluginSpec(
                id=p.get("id", ""),
                name=p.get("name", ""),
                version=p.get("version", "0.0.1"),
                type=p.get("type", "unknown"),
                language=p.get("language", "MATLAB"),
                entry=p.get("entry", ""),
                status=p.get("status", "candidate"),
            )

            # 兼容性
            comp = data.get("compatibility") or {}
            spec.dimensions = comp.get("dimensions", [2, 3])
            spec.requires_chain_gradient = bool(
                comp.get("requires_chain_gradient", False))
            spec.dependencies = list(comp.get("dependencies") or [])
            spec.mutual_exclusion = list(comp.get("mutual_exclusion") or [])
            spec.supported_solvers = list(comp.get("solvers") or [])
            spec.supported_optimizers = list(comp.get("optimizers") or [])

            # 参数 / 限制 / 证据
            spec.parameters = list(data.get("parameters") or [])
            spec.known_failure_modes = list(data.get("limitations") or [])
            ev = data.get("evidence") or {}
            spec.paper_doi = ev.get("paper_doi", "")
            spec.paper_pages = list(ev.get("pages") or [])
            spec.paper_figures = list(ev.get("figures") or [])

            # 验证状态
            v = data.get("verification") or {}
            spec.verification_tests = {
                "unit_test": bool(v.get("unit_test", False)),
                "finite_difference": bool(v.get("finite_difference_test", False)),
                "benchmark_mbb": bool(v.get("mbb_reproduction", False)),
                "benchmark_3d": bool(v.get("cantilever_3d", False)),
                "cpu_gpu_consistency": bool(v.get("cpu_gpu_consistency", False)),
            }
            spec.verified_by = v.get("verified_by", "")
            spec.implementation_commit = v.get("implementation_commit", "")

            self.register(spec)

    def to_json(self) -> str:
        """输出注册表为JSON"""
        data = {}
        for pid, spec in self._plugins.items():
            data[pid] = {
                "id": spec.id, "name": spec.name, "version": spec.version,
                "type": spec.type, "status": spec.status
            }
        return json.dumps(data, indent=2, ensure_ascii=False)