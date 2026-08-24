import type { ProjectEntry } from "./types";

export interface ProjectTreeNode {
  name: string;
  path: string;
  kind: "directory" | "file";
  entry?: ProjectEntry;
  children?: ProjectTreeNode[];
}

function sortNodes(nodes: ProjectTreeNode[]): ProjectTreeNode[] {
  nodes.sort((left, right) => {
    if (left.kind !== right.kind) return left.kind === "directory" ? -1 : 1;
    return left.name.localeCompare(right.name, undefined, { sensitivity: "base" });
  });
  for (const node of nodes) {
    if (node.children) sortNodes(node.children);
  }
  return nodes;
}

export function buildProjectTree(entries: ProjectEntry[]): ProjectTreeNode[] {
  const root: ProjectTreeNode[] = [];
  for (const entry of entries) {
    if (entry.kind !== "file") continue;
    const normalized = entry.relative_path.replaceAll("\\", "/");
    if (!normalized || normalized.startsWith("/") || /^[A-Za-z]:/.test(normalized)) continue;
    const parts = normalized.split("/");
    if (parts.some(part => !part || part === "." || part === "..")) continue;

    let children = root;
    for (let index = 0; index < parts.length - 1; index++) {
      const path = parts.slice(0, index + 1).join("/");
      let directory = children.find(node => node.kind === "directory" && node.name === parts[index]);
      if (!directory) {
        directory = { name: parts[index], path, kind: "directory", children: [] };
        children.push(directory);
      }
      children = directory.children!;
    }
    const name = parts.at(-1)!;
    if (!children.some(node => node.path === normalized)) {
      children.push({ name, path: normalized, kind: "file", entry });
    }
  }
  return sortNodes(root);
}