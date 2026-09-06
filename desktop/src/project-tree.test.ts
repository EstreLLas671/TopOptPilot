import { describe, expect, it } from "vitest";
import { buildProjectTree } from "./project-tree";

describe("project tree", () => {
  it("infers nested directories from the flat secure project file list", () => {
    const tree = buildProjectTree([
      { relative_path: "README.md", kind: "file", size_bytes: 20 },
      { relative_path: "matlab/solver/topopt3d_main.m", kind: "file", size_bytes: 40 },
      { relative_path: "matlab/FE_solver_3d.m", kind: "file", size_bytes: 30 },
      { relative_path: "configs/default.json", kind: "file", size_bytes: 10 },
    ]);

    expect(tree.map(node => [node.name, node.kind])).toEqual([
      ["configs", "directory"],
      ["matlab", "directory"],
      ["README.md", "file"],
    ]);
    expect(tree[1].children?.map(node => node.name)).toEqual([
      "solver",
      "FE_solver_3d.m",
    ]);
    expect(tree[1].children?.[0].children?.[0]).toMatchObject({
      name: "topopt3d_main.m",
      path: "matlab/solver/topopt3d_main.m",
      kind: "file",
    });
  });

  it("normalizes separators and rejects path traversal segments", () => {
    expect(buildProjectTree([
      { relative_path: "src\\main.m", kind: "file", size_bytes: 10 },
      { relative_path: "../outside.m", kind: "file", size_bytes: 10 },
    ])).toMatchObject([{ name: "src", kind: "directory" }]);
  });
});