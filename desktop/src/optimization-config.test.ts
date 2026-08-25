import { describe, expect, it } from "vitest";
import { DEFAULT_OPTIMIZATION_CONFIG, engineeringTaskFromConfig, validateOptimizationConfig } from "./optimization-config";

describe("optimization config", () => {
  it("keeps the legacy iDeskTop defaults and emits the complete run task", () => {
    expect(DEFAULT_OPTIMIZATION_CONFIG).toEqual({
      dimension: "3d", bcType: "cantilever", accuracy: "standard", nelx: 24, nely: 8, nelz: 6,
      volfrac: 0.4, penal: 3, rmin: 1.5, maxIterations: 60,
      minIterations: 10, filterStrategy: "fixed",
    });
    expect(engineeringTaskFromConfig(DEFAULT_OPTIMIZATION_CONFIG)).toEqual({
      task_id: "idesktop-v2-ui",
      dimension: "3d",
      load_case: "cantilever",
      geometry: { nelx: 24, nely: 8, nelz: 6 },
      params: { volfrac: 0.4, penal: 3, rmin: 1.5, max_iter: 60, min_iter: 10, filter_strategy: "fixed", accuracy: "standard" },
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
});