export type BuiltInCase = "cantilever" | "MBB" | "simply_supported" | "L-bracket";
export type Accuracy = "standard" | "high";
export type FilterStrategy = "fixed" | "adaptive";
export type SolverDimension = "2d" | "3d";
export type MaterialPreset = "normalized" | "structural-steel" | "aluminum-6061-t6" | "titanium-ti6al4v" | "custom";

export type MaterialConfig = {
  preset: MaterialPreset;
  name: string;
  youngsModulusGPa: number;
  poissonRatio: number;
  densityKgM3: number;
  yieldStrengthMPa: number;
};

export const MATERIAL_PRESETS: Record<Exclude<MaterialPreset, "custom">, MaterialConfig> = {
  normalized: { preset: "normalized", name: "归一化参考材料", youngsModulusGPa: 1, poissonRatio: 0.3, densityKgM3: 1, yieldStrengthMPa: 1 },
  "structural-steel": { preset: "structural-steel", name: "结构钢", youngsModulusGPa: 200, poissonRatio: 0.3, densityKgM3: 7850, yieldStrengthMPa: 250 },
  "aluminum-6061-t6": { preset: "aluminum-6061-t6", name: "6061-T6 铝合金", youngsModulusGPa: 68.9, poissonRatio: 0.33, densityKgM3: 2700, yieldStrengthMPa: 276 },
  "titanium-ti6al4v": { preset: "titanium-ti6al4v", name: "Ti-6Al-4V 钛合金", youngsModulusGPa: 113.8, poissonRatio: 0.342, densityKgM3: 4430, yieldStrengthMPa: 880 },
};

export function materialForPreset(preset: MaterialPreset, current?: MaterialConfig): MaterialConfig {
  if (preset === "custom") {
    return {
      preset,
      name: current?.preset === "custom" ? current.name : "自定义材料",
      youngsModulusGPa: current?.youngsModulusGPa ?? 1,
      poissonRatio: current?.poissonRatio ?? 0.3,
      densityKgM3: current?.densityKgM3 ?? 1000,
      yieldStrengthMPa: current?.yieldStrengthMPa ?? 1,
    };
  }
  return { ...MATERIAL_PRESETS[preset] };
}

export type OptimizationConfig = {
  dimension: SolverDimension;
  bcType: BuiltInCase;
  accuracy: Accuracy;
  nelx: number;
  nely: number;
  nelz: number;
  volfrac: number;
  penal: number;
  rmin: number;
  maxIterations: number;
  minIterations: number;
  filterStrategy: FilterStrategy;
  material: MaterialConfig;
};

export type OptimizationConfigAction = {
  type: "apply_optimization_config";
  config: OptimizationConfig;
  changedFields: string[];
  rationale?: string;
};

export const DEFAULT_OPTIMIZATION_CONFIG: OptimizationConfig = {
  dimension: "3d",
  bcType: "cantilever",
  accuracy: "standard",
  nelx: 24,
  nely: 8,
  nelz: 6,
  volfrac: 0.4,
  penal: 3,
  rmin: 1.5,
  maxIterations: 60,
  minIterations: 10,
  material: materialForPreset("normalized"),
  filterStrategy: "fixed",
};

export function validateOptimizationConfig(config: OptimizationConfig): string[] {
  const errors: string[] = [];
  if (!["2d", "3d"].includes(config.dimension)) errors.push("求解维度仅支持 2D 或 3D");
  if (!["cantilever", "MBB", "simply_supported", "L-bracket"].includes(config.bcType)) errors.push("工况不是受支持的内置类型");
  if (!["standard", "high"].includes(config.accuracy)) errors.push("精度仅支持标准或高精度");
  if (!["fixed", "adaptive"].includes(config.filterStrategy)) errors.push("滤波策略仅支持固定或自适应半径");
  for (const key of ["nelx", "nely", "nelz"] as const) {
    if (!Number.isInteger(config[key]) || config[key] <= 0) errors.push(`${key} 必须是正整数`);
  }
  if (!(config.volfrac > 0 && config.volfrac <= 1)) errors.push("体积分数必须大于 0 且不超过 1");
  if (!(config.penal >= 1 && config.penal <= 5)) errors.push("惩罚因子必须在 1 到 5 之间");
  if (!(config.rmin > 0)) errors.push("滤波半径必须大于 0");
  if (!Number.isInteger(config.maxIterations) || config.maxIterations < 1) errors.push("最大迭代必须是正整数");
  if (!Number.isInteger(config.minIterations) || config.minIterations < 1) errors.push("最小迭代必须是正整数");
  if (config.minIterations > config.maxIterations) errors.push("最小迭代不能大于最大迭代");
  if (!config.material || !["normalized", "structural-steel", "aluminum-6061-t6", "titanium-ti6al4v", "custom"].includes(config.material.preset)) {
    errors.push("材料类型无效");
  } else {
    if (!config.material.name.trim() || config.material.name.trim().length > 80) errors.push("材料名称必须为 1–80 个字符");
    if (!(Number.isFinite(config.material.youngsModulusGPa) && config.material.youngsModulusGPa > 0)) errors.push("杨氏模量必须大于 0");
    if (!(Number.isFinite(config.material.poissonRatio) && config.material.poissonRatio > -1 && config.material.poissonRatio < 0.5)) errors.push("泊松比必须大于 -1 且小于 0.5");
    if (!(Number.isFinite(config.material.densityKgM3) && config.material.densityKgM3 > 0)) errors.push("材料密度必须大于 0");
    if (!(Number.isFinite(config.material.yieldStrengthMPa) && config.material.yieldStrengthMPa > 0)) errors.push("屈服强度必须大于 0");
  }
  return errors;
}

export function parseOptimizationConfigAction(value: unknown): OptimizationConfigAction | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  if (raw.type !== "apply_optimization_config" || !raw.config || typeof raw.config !== "object") return null;
  const config = raw.config as OptimizationConfig;
  if (validateOptimizationConfig(config).length) return null;
  if (!Array.isArray(raw.changedFields) || !raw.changedFields.every(item => typeof item === "string")) return null;
  return {
    type: "apply_optimization_config",
    config,
    changedFields: raw.changedFields,
    rationale: typeof raw.rationale === "string" ? raw.rationale : undefined,
  };
}

export function engineeringTaskFromConfig(config: OptimizationConfig) {
  return {
    task_id: "idesktop-v2-ui",
    dimension: config.dimension,
    load_case: config.bcType,
    geometry: { nelx: config.nelx, nely: config.nely, nelz: config.dimension === "2d" ? 1 : config.nelz },
    material: {
      preset: config.material.preset,
      name: config.material.name.trim(),
      E: config.material.youngsModulusGPa,
      E_GPa: config.material.youngsModulusGPa,
      nu: config.material.poissonRatio,
      density_kg_m3: config.material.densityKgM3,
      yield_strength_MPa: config.material.yieldStrengthMPa,
    },
    params: {
      volfrac: config.volfrac,
      penal: config.penal,
      rmin: config.rmin,
      max_iter: config.maxIterations,
      min_iter: config.minIterations,
      filter_strategy: config.filterStrategy,
      accuracy: config.accuracy,
      E: config.material.youngsModulusGPa,
      nu: config.material.poissonRatio,
    },
  };
}
