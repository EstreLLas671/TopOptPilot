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
  dimensions: [number, number, number];
  unit: string;
  cellSizeMeters: number;
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

export const DEFAULT_CELL_SIZE_METERS = 0.25;
const UNIT_TO_METERS: Record<string, number> = { m: 1, mm: 1e-3, cm: 1e-2, um: 1e-6 };

export function dimensionsToGrid(dimensions: readonly number[], dimension: SolverDimension, unit = "m", cellSizeMeters = DEFAULT_CELL_SIZE_METERS): [number, number, number] {
  const scale = UNIT_TO_METERS[unit.trim().toLowerCase()] ?? 1;
  const safeCell = Number.isFinite(cellSizeMeters) && cellSizeMeters > 0 ? cellSizeMeters : DEFAULT_CELL_SIZE_METERS;
  const values = dimensions.slice(0, dimension === "2d" ? 2 : 3).map(value => Math.max(1, Math.ceil((Number(value) * scale) / safeCell)));
  return [values[0] || 1, values[1] || 1, dimension === "2d" ? 1 : (values[2] || 1)];
}
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
  dimensions: [6, 2, 1.5],
  unit: "m",
  cellSizeMeters: DEFAULT_CELL_SIZE_METERS,

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

export function normalizeOptimizationConfig(value: Partial<OptimizationConfig> | null | undefined): OptimizationConfig {
  const source = value || {};
  const dimension = source.dimension === "2d" ? "2d" : "3d";
  const dimensions = (Array.isArray(source.dimensions) && source.dimensions.length >= 2
    ? [Number(source.dimensions[0]), Number(source.dimensions[1]), Number(source.dimensions[2] ?? DEFAULT_OPTIMIZATION_CONFIG.dimensions[2])]
    : [Number(source.nelx ?? DEFAULT_OPTIMIZATION_CONFIG.nelx) * DEFAULT_CELL_SIZE_METERS, Number(source.nely ?? DEFAULT_OPTIMIZATION_CONFIG.nely) * DEFAULT_CELL_SIZE_METERS, Number(source.nelz ?? DEFAULT_OPTIMIZATION_CONFIG.nelz) * DEFAULT_CELL_SIZE_METERS]) as [number, number, number];
  const normalized = { ...DEFAULT_OPTIMIZATION_CONFIG, ...source, dimension, dimensions, unit: source.unit || "m", cellSizeMeters: Number(source.cellSizeMeters) > 0 ? Number(source.cellSizeMeters) : DEFAULT_CELL_SIZE_METERS, material: { ...DEFAULT_OPTIMIZATION_CONFIG.material, ...(source.material || {}) } } as OptimizationConfig;
  const [nelx, nely, nelz] = dimensionsToGrid(normalized.dimensions, normalized.dimension, normalized.unit, normalized.cellSizeMeters);
  return { ...normalized, nelx, nely, nelz };
}
export function validateOptimizationConfig(config: OptimizationConfig): string[] {
  const errors: string[] = [];
  if (!["2d", "3d"].includes(config.dimension)) errors.push("求解维度仅支持 2D 或 3D");
  if (!["cantilever", "MBB", "simply_supported", "L-bracket"].includes(config.bcType)) errors.push("工况不是受支持的内置类型");
  if (!["standard", "high"].includes(config.accuracy)) errors.push("精度仅支持标准或高精度");
  if (!["fixed", "adaptive"].includes(config.filterStrategy)) errors.push("滤波策略仅支持固定或自适应半径");
  if (!Array.isArray(config.dimensions) || config.dimensions.length < 2 || (config.dimension === "3d" && config.dimensions.length < 3)) errors.push("几何尺寸必须包含有效的长、宽及高（3D）");
  else config.dimensions.slice(0, config.dimension === "2d" ? 2 : 3).forEach((value, index) => { if (!(Number.isFinite(value) && value > 0)) errors.push(["长(X)", "宽(Y)", "高(Z)"][index] + "必须为正数"); });
  if (!["m", "mm", "cm", "um"].includes(String(config.unit || "").trim().toLowerCase())) errors.push("尺寸单位仅支持 m、mm、cm 或 um");
  if (!(Number.isFinite(config.cellSizeMeters) && config.cellSizeMeters > 0)) errors.push("单元网格尺寸必须为正数");
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
  const grid = dimensionsToGrid(config.dimensions, config.dimension, config.unit, config.cellSizeMeters);
  const cellSizeMeters = [0, 1, 2].map(index => config.dimension === "2d" && index === 2 ? 0 : (index < 3 && grid[index] > 0 ? Number(config.dimensions[index]) * (UNIT_TO_METERS[config.unit] ?? 1) / grid[index] : 0)) as [number, number, number];
  return {
    task_id: "topoptpilot-ui",
    dimension: config.dimension,
    load_case: config.bcType,
    geometry: { nelx: grid[0], nely: grid[1], nelz: grid[2], dimensions: config.dimensions.slice(0, config.dimension === "2d" ? 2 : 3), unit: config.unit, cellSizeMeters, cell_size_m: config.cellSizeMeters },
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
      grid3d: config.dimension === "3d" ? grid : undefined,
    },
  };
}
