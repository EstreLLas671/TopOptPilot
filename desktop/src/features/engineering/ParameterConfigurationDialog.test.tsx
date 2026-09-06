// @vitest-environment jsdom

import { useState } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_OPTIMIZATION_CONFIG, type OptimizationConfig } from "../../optimization-config";
import type { EngineeringSolverLane } from "../../engineering-workspace";
import ParameterConfigurationDialog from "./ParameterConfigurationDialog";

type HarnessProps = {
  onApply?: (config: OptimizationConfig, lane: EngineeringSolverLane) => void;
};

function Harness({ onApply = () => undefined }: HarnessProps) {
  const [open, setOpen] = useState(false);
  return <>
    <button onClick={() => setOpen(true)}>打开参数</button>
    <ParameterConfigurationDialog
      open={open}
      config={DEFAULT_OPTIMIZATION_CONFIG}
      lane="local-matlab"
      busy={false}
      matlabDiagnostic="MATLAB 已就绪"
      runtimeDiagnostic="Runtime 未配置"
      onClose={() => setOpen(false)}
      onApply={(config, lane) => {
        onApply(config, lane);
        setOpen(false);
      }}
    />
  </>;
}

describe("ParameterConfigurationDialog", () => {
  afterEach(cleanup);

  it("traps keyboard focus and restores it to the opener", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "打开参数" });

    await user.click(opener);
    const close = screen.getByRole("button", { name: "关闭详细参数" });
    await waitFor(() => expect(document.activeElement).toBe(close));

    await user.tab({ shift: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "应用配置" }));
    await user.tab();
    expect(document.activeElement).toBe(close);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("keeps edits as a draft until Apply is selected", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<Harness onApply={onApply} />);

    await user.click(screen.getByRole("button", { name: "打开参数" }));
    const cellSize = screen.getByLabelText("单元网格尺寸（m）") as HTMLInputElement;
    await user.clear(cellSize);
    await user.type(cellSize, "0.125");
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(onApply).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "打开参数" }));
    expect((screen.getByLabelText("单元网格尺寸（m）") as HTMLInputElement).value).toBe("0.25");
    await user.clear(screen.getByLabelText("单元网格尺寸（m）"));
    await user.type(screen.getByLabelText("单元网格尺寸（m）"), "0.125");
    await user.click(screen.getByRole("button", { name: "应用配置" }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0][0]).toMatchObject({ cellSizeMeters: 0.125, nelx: 48, dimension: "3d" });
    expect(onApply.mock.calls[0][1]).toBe("local-matlab");
  });

  it("shows only MATLAB and Python and removes redundant validation copy", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "打开参数" }));

    const lane = screen.getByLabelText("求解链路") as HTMLSelectElement;
    expect(lane.value).toBe("local-matlab");
    expect(Array.from(lane.options).map(option => option.value)).toEqual(["local-matlab", "python-fem"]);
    expect(screen.queryByText(/修改暂存在此窗口/)).toBeNull();
    expect(screen.queryByText("配置校验通过")).toBeNull();
  });

  it("supports classic presets and applies a custom material", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();
    render(<Harness onApply={onApply} />);

    await user.click(screen.getByRole("button", { name: "打开参数" }));
    await user.selectOptions(screen.getByLabelText("材料预设"), "structural-steel");
    const presetName = screen.getByLabelText("材料名称") as HTMLInputElement;
    expect(presetName.value).toBe("结构钢");
    expect(presetName.readOnly).toBe(true);
    expect(screen.getByText("E 200 GPa · ν 0.3")).toBeTruthy();

    await user.selectOptions(screen.getByLabelText("材料预设"), "custom");
    const values: Array<[string, string]> = [["材料名称", "测试复合材料"], ["杨氏模量 E（GPa）", "72"], ["泊松比 ν", "0.31"], ["密度（kg/m³）", "1600"], ["屈服强度（MPa）", "420"]];
    for (const [label, value] of values) {
      const input = screen.getByLabelText(label);
      await user.clear(input);
      await user.type(input, value);
    }
    expect(screen.getByText("ρ 1600 kg/m³ · σy 420 MPa")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "应用配置" }));

    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({
      material: { preset: "custom", name: "测试复合材料", youngsModulusGPa: 72, poissonRatio: 0.31, densityKgM3: 1600, yieldStrengthMPa: 420 },
    }), "local-matlab");
  });
});
