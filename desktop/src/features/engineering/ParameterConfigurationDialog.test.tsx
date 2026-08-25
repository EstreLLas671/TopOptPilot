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
    const xUnits = screen.getByLabelText("X 单元") as HTMLInputElement;
    await user.clear(xUnits);
    await user.type(xUnits, "48");
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(onApply).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "打开参数" }));
    expect((screen.getByLabelText("X 单元") as HTMLInputElement).value).toBe("24");
    await user.clear(screen.getByLabelText("X 单元"));
    await user.type(screen.getByLabelText("X 单元"), "48");
    await user.click(screen.getByRole("button", { name: "应用配置" }));

    expect(onApply).toHaveBeenCalledTimes(1);
    expect(onApply.mock.calls[0][0]).toMatchObject({ nelx: 48, dimension: "3d" });
    expect(onApply.mock.calls[0][1]).toBe("local-matlab");
  });
});
