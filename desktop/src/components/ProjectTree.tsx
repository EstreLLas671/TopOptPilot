import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen } from "lucide-react";
import type { ProjectEntry, ProjectFile } from "../types";
import { buildProjectTree, type ProjectTreeNode } from "../project-tree";

type Props = {
  entries: ProjectEntry[];
  selected: ProjectFile | null;
  disabled?: boolean;
  onOpen: (entry: ProjectEntry) => void;
};

export default function ProjectTree({ entries, selected, disabled = false, onOpen }: Props) {
  const tree = useMemo(() => buildProjectTree(entries), [entries]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const toggle = (path: string) => setExpanded(previous => {
    const next = new Set(previous);
    if (next.has(path)) next.delete(path); else next.add(path);
    return next;
  });

  return <div className="project-tree" role="tree" aria-label="项目文件树">
    {tree.map(node => <ProjectTreeRow key={node.path} node={node} depth={0} expanded={expanded} disabled={disabled} selectedPath={selected?.relative_path || ""} onToggle={toggle} onOpen={onOpen}/>)}
    {!tree.length ? <div className="project-tree-empty">项目文件将在这里按目录显示。</div> : null}
  </div>;
}

function ProjectTreeRow({ node, depth, expanded, disabled, selectedPath, onToggle, onOpen }: {
  node: ProjectTreeNode;
  depth: number;
  expanded: Set<string>;
  disabled: boolean;
  selectedPath: string;
  onToggle: (path: string) => void;
  onOpen: (entry: ProjectEntry) => void;
}) {
  const open = node.kind === "directory" && expanded.has(node.path);
  if (node.kind === "directory") {
    return <div role="treeitem" aria-expanded={open}>
      <button className="project-tree-row directory" style={{ paddingLeft: 8 + depth * 15 }} onClick={() => onToggle(node.path)}>
        {open ? <ChevronDown size={12}/> : <ChevronRight size={12}/>}
        {open ? <FolderOpen size={13}/> : <Folder size={13}/>}
        <span>{node.name}</span>
      </button>
      {open ? <div role="group">{node.children?.map(child => <ProjectTreeRow key={child.path} node={child} depth={depth + 1} expanded={expanded} disabled={disabled} selectedPath={selectedPath} onToggle={onToggle} onOpen={onOpen}/>)}</div> : null}
    </div>;
  }
  return <button role="treeitem" className={`project-tree-row file ${selectedPath === node.path ? "active" : ""}`} style={{ paddingLeft: 23 + depth * 15 }} disabled={disabled} onClick={() => node.entry && onOpen(node.entry)}>
    <FileCode2 size={13}/><span>{node.name}</span><small>{node.entry ? formatBytes(node.entry.size_bytes) : ""}</small>
  </button>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}
