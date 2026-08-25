export type BuiltInCase = "cantilever" | "MBB" | "simply_supported" | "L-bracket";
export type Accuracy = "standard" | "high";
export type FilterStrategy = "fixed" | "adaptive";
export type SolverDimension = "2d" | "3d";

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
  return errors;
}

export function engineeringTaskFromConfig(config: OptimizationConfig) {
  return {
    task_id: "idesktop-v2-ui",
    dimension: config.dimension,
    load_case: config.bcType,
    geometry: { nelx: config.nelx, nely: config.nely, nelz: config.dimension === "2d" ? 1 : config.nelz },
    params: {
      volfrac: config.volfrac,
      penal: config.penal,
      rmin: config.rmin,
      max_iter: config.maxIterations,
      min_iter: config.minIterations,
      filter_strategy: config.filterStrategy,
      accuracy: config.accuracy,
    },
  };
}
