// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ProjectTree from "./ProjectTree";

describe("ProjectTree", () => {
  it("keeps nested project files collapsed until their parent is opened", () => {
    render(
      <ProjectTree
        entries={[
          { relative_path: "README.md", kind: "file", size_bytes: 20 },
          { relative_path: "matlab/solver/topopt_main.m", kind: "file", size_bytes: 40 },
        ]}
        selected={null}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.queryByText("topopt_main.m")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "matlab" }));
    expect(screen.queryByText("topopt_main.m")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "solver" }));
    expect(screen.getByText("topopt_main.m")).toBeTruthy();
  });
});
