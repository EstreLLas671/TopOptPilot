import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type CSSProperties } from "react";
import { ChevronLeft, ChevronRight, GripVertical, PanelBottom, PanelBottomClose, PanelRight, PanelRightClose, RotateCcw, SlidersHorizontal } from "lucide-react";
import {
  clampLayout,
  DEFAULT_LAYOUT,
  loadWorkspaceLayout,
  resetWorkspaceLayout,
  saveWorkspaceLayout,
  togglePanel,
  type PanelName,
  type WorkspaceLayout,
} from "../layout-state";
import type { WorkspaceMode } from "../workspace";

type Props = {
  mode: WorkspaceMode;
  left: ReactNode;
  leftRail?: ReactNode;
  center: ReactNode;
  right: ReactNode;
  bottom: ReactNode;
  activitySignal?: string;
};

type ResizePanel = "left" | "right" | "bottom";

export default function ResizableWorkspaceLayout({ mode, left, leftRail, center, right, bottom, activitySignal = "" }: Props) {
  const [layout, setLayout] = useState<WorkspaceLayout>(() => loadWorkspaceLayout(mode));
  const [resizing, setResizing] = useState<ResizePanel | null>(null);
  const [layoutMode, setLayoutMode] = useState<WorkspaceMode>(mode);
  const layoutRef = useRef(layout);
  const resizeRef = useRef<{ panel: ResizePanel; x: number; y: number; start: WorkspaceLayout } | null>(null);
  const consumedActivity = useRef("");

  useEffect(() => {
    const next = loadWorkspaceLayout(mode);
    setLayoutMode(mode);
    layoutRef.current = next;
    setLayout(next);
    consumedActivity.current = "";
  }, [mode]);

  useEffect(() => {
    if (layoutMode !== mode) return;
    layoutRef.current = layout;
    saveWorkspaceLayout(mode, layout);
  }, [layout, layoutMode, mode]);

  useEffect(() => {
    if (!activitySignal || consumedActivity.current === activitySignal) return;
    consumedActivity.current = activitySignal;
    if (!layoutRef.current.bottomOpen) {
      const next = { ...layoutRef.current, bottomOpen: true };
      layoutRef.current = next;
      setLayout(next);
    }
  }, [activitySignal]);

  const updateLayout = useCallback((next: WorkspaceLayout) => {
    const normalized = clampLayout(next, { viewportWidth: window.innerWidth });
    layoutRef.current = normalized;
    setLayout(normalized);
  }, []);

  const stopResize = useCallback(() => {
    if (!resizeRef.current) return;
    resizeRef.current = null;
    setResizing(null);
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
  }, []);

  const moveResize = useCallback((event: PointerEvent) => {
    const flight = resizeRef.current;
    if (!flight) return;
    const dx = event.clientX - flight.x;
    const dy = event.clientY - flight.y;
    const next = { ...flight.start };
    if (flight.panel === "left") next.leftWidth = flight.start.leftWidth + dx;
    if (flight.panel === "right") next.rightWidth = flight.start.rightWidth - dx;
    if (flight.panel === "bottom") next.bottomHeight = flight.start.bottomHeight - dy;
    updateLayout(next);
  }, [updateLayout]);

  useEffect(() => {
    if (!resizing) return;
    window.addEventListener("pointermove", moveResize);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
    return () => {
      window.removeEventListener("pointermove", moveResize);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
    };
  }, [moveResize, resizing, stopResize]);

  const startResize = useCallback((panel: ResizePanel, event: ReactPointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    resizeRef.current = { panel, x: event.clientX, y: event.clientY, start: layoutRef.current };
    setResizing(panel);
    document.body.style.userSelect = "none";
    document.body.style.cursor = panel === "bottom" ? "ns-resize" : "ew-resize";
  }, []);

  const resizeWithKeyboard = useCallback((panel: ResizePanel, event: ReactKeyboardEvent<HTMLButtonElement>) => {
    const step = event.shiftKey ? 24 : 8;
    const next = { ...layoutRef.current };
    if (panel === "left" && event.key === "ArrowLeft") next.leftWidth -= step;
    else if (panel === "left" && event.key === "ArrowRight") next.leftWidth += step;
    else if (panel === "right" && event.key === "ArrowLeft") next.rightWidth += step;
    else if (panel === "right" && event.key === "ArrowRight") next.rightWidth -= step;
    else if (panel === "bottom" && event.key === "ArrowUp") next.bottomHeight += step;
    else if (panel === "bottom" && event.key === "ArrowDown") next.bottomHeight -= step;
    else return;
    event.preventDefault();
    updateLayout(next);
  }, [updateLayout]);

  const setPanel = useCallback((panel: PanelName) => updateLayout(togglePanel(layoutRef.current, panel)), [updateLayout]);
  const reset = useCallback(() => updateLayout(resetWorkspaceLayout(mode)), [mode, updateLayout]);

  return <main
    className={`v2-workspace resizable-workspace ${resizing ? "is-resizing" : ""}`}
    style={{
      "--left-track": layout.leftOpen ? `${layout.leftWidth}px` : "48px",
      "--right-track": layout.rightOpen ? `${layout.rightWidth}px` : "0px",
      "--left-handle": layout.leftOpen ? "2px" : "0px",
      "--right-handle": layout.rightOpen ? "2px" : "0px",
      "--bottom-rows": layout.bottomOpen ? `minmax(0, 1fr) 2px ${layout.bottomHeight}px` : "minmax(0, 1fr)",
    } as CSSProperties}
    data-workspace={mode}
  >
    {layout.leftOpen ? <aside className="v2-sidebar workspace-panel workspace-left" data-panel="left">{left}<div className="workspace-mobile-left-rail">{leftRail}</div><button className="panel-toggle panel-toggle-left" aria-label="隐藏左侧项目栏" title="隐藏左侧项目栏" onClick={() => setPanel("left")}><ChevronLeft size={13}/></button></aside> : <aside className="workspace-left-rail" data-panel="left-rail" onClick={event => { if ((event.target as HTMLElement).closest(".left-rail-icons button")) setPanel("left"); }}><button className="panel-restore panel-restore-left" aria-label="显示左侧项目栏" title="显示左侧项目栏" onClick={() => setPanel("left")}><ChevronRight size={14}/></button>{leftRail || <div className="left-rail-fallback"><SlidersHorizontal size={15}/></div>}</aside>}
    {layout.leftOpen ? <button className="panel-resize panel-resize-left" role="separator" aria-label="调整左侧面板宽度" aria-orientation="vertical" aria-valuemin={240} aria-valuemax={420} aria-valuenow={layout.leftWidth} title="拖动或用方向键调整左侧面板" onKeyDown={event => resizeWithKeyboard("left", event)} onPointerDown={event => startResize("left", event)}><GripVertical size={10}/></button> : null}
    <section className="workspace-main-column">
      <section className="v2-center workspace-center">{center}<div className="center-toolbar-actions" aria-label="中央工作区面板控制"><button className="center-panel-action" aria-pressed={layout.bottomOpen} aria-label={layout.bottomOpen ? "隐藏底部面板" : "显示底部面板"} title={layout.bottomOpen ? "隐藏底部面板" : "显示底部面板"} onClick={() => setPanel("bottom")}>{layout.bottomOpen ? <PanelBottomClose size={16}/> : <PanelBottom size={16}/>}</button><button className="center-panel-action" aria-pressed={layout.rightOpen} aria-label={layout.rightOpen ? "隐藏右侧检查器" : "显示右侧检查器"} title={layout.rightOpen ? "隐藏右侧检查器" : "显示右侧检查器"} onClick={() => setPanel("right")}>{layout.rightOpen ? <PanelRightClose size={16}/> : <PanelRight size={16}/>}</button></div></section>
      {layout.bottomOpen ? <><button className="panel-resize panel-resize-bottom" role="separator" aria-label="调整底部面板高度" aria-orientation="horizontal" aria-valuemin={180} aria-valuemax={520} aria-valuenow={layout.bottomHeight} title="拖动或用方向键调整底部面板" onKeyDown={event => resizeWithKeyboard("bottom", event)} onPointerDown={event => startResize("bottom", event)}><GripVertical size={10}/></button><section className="workspace-bottom">{bottom}</section></> : null}
    </section>
    {layout.rightOpen ? <button className="panel-resize panel-resize-right" role="separator" aria-label="调整右侧面板宽度" aria-orientation="vertical" aria-valuemin={320} aria-valuemax={520} aria-valuenow={layout.rightWidth} title="拖动或用方向键调整右侧面板" onKeyDown={event => resizeWithKeyboard("right", event)} onPointerDown={event => startResize("right", event)}><GripVertical size={10}/></button> : null}
    {layout.rightOpen ? <aside className="v2-inspector workspace-panel workspace-right" data-panel="right">{right}</aside> : null}
    <button className="layout-reset" aria-label="重置当前工作区布局" title="重置当前工作区布局" onClick={reset}><RotateCcw size={12}/></button>
  </main>;
}

export { DEFAULT_LAYOUT };
