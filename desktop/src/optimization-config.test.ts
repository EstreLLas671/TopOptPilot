import { describe, expect, it } from "vitest";
import { DEFAULT_OPTIMIZATION_CONFIG, engineeringTaskFromConfig, validateOptimizationConfig } from "./optimization-config";

describe("optimization config", () => {
  it("keeps the legacy iDeskTop defaults and emits the complete run task", () => {
    expect(DEFAULT_OPTIMIZATION_CONFIG).toEqual({
      dimension: "3d", bcType: "cantilever", accuracy: "standard", nelx: 24, nely: 8, nelz: 6,
      volfrac: 0.4, penal: 3, rmin: 1.5, maxIterations: 60,
      minIterations: 10, filterStrategy: "fixed",
      material: { preset: "normalized", name: "归一化参考材料", youngsModulusGPa: 1, poissonRatio: 0.3, densityKgM3: 1, yieldStrengthMPa: 1 },
    });
    expect(engineeringTaskFromConfig(DEFAULT_OPTIMIZATION_CONFIG)).toEqual({
      task_id: "idesktop-v2-ui",
      dimension: "3d",
      load_case: "cantilever",
      geometry: { nelx: 24, nely: 8, nelz: 6 },
      material: { preset: "normalized", name: "归一化参考材料", E: 1, E_GPa: 1, nu: 0.3, density_kg_m3: 1, yield_strength_MPa: 1 },
      params: { volfrac: 0.4, penal: 3, rmin: 1.5, max_iter: 60, min_iter: 10, filter_strategy: "fixed", accuracy: "standard", E: 1, nu: 0.3 },
    });
  });

  it("emits the 2D solver dimension and forces a single z layer", () => {
    const task = engineeringTaskFromConfig({ ...DEFAULT_OPTIMIZATION_CONFIG, dimension: "2d", nelz: 9 });
    expect(task.dimension).toBe("2d");
    expect(task.geometry).toEqual({ nelx: 24, nely: 8, nelz: 1 });
  });

  it("rejects invalid volume, penalty, radius, grid and iteration ranges", () => {
    expect(validateOptimizationConfig({ ...DEFAULT_OPTIMIZATION_CONFIG, nelx: 0, volfrac: 2, penal: 0, rmin: 0, minIterations: 61 })).toHaveLength(5);
  });


  it("validates custom material properties", () => {
    const invalid = { ...DEFAULT_OPTIMIZATION_CONFIG, material: { preset: "custom" as const, name: "", youngsModulusGPa: 0, poissonRatio: 0.5, densityKgM3: 0, yieldStrengthMPa: 0 } };
    expect(validateOptimizationConfig(invalid)).toEqual([
      "材料名称必须为 1–80 个字符", "杨氏模量必须大于 0", "泊松比必须大于 -1 且小于 0.5", "材料密度必须大于 0", "屈服强度必须大于 0",
    ]);
  });
});