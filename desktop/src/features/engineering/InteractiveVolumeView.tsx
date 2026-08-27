import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Maximize2, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { fortranVolumeValue, type MatlabVolume } from "./matlab-artifact";

type FieldMode = "density" | "stress";
type ViewMode = "surface" | "cells";
export type ViewState = { rotationX: number; rotationY: number; zoom: number };
type Point3 = { x: number; y: number; z: number };
type Face = { points: Point3[]; depth: number; value: number; light: number };

const ISO_LEVEL = 0.5;
const DEFAULT_VIEW: ViewState = { rotationX: -0.52, rotationY: 0.72, zoom: 1 };
const CUBE_VERTICES = [
  [0, 0, 0], [0, 1, 0], [1, 1, 0], [1, 0, 0],
  [0, 0, 1], [0, 1, 1], [1, 1, 1], [1, 0, 1],
] as const;
const CUBE_TETRAHEDRA = [
  [0, 5, 1, 6], [0, 1, 2, 6], [0, 2, 3, 6],
  [0, 3, 7, 6], [0, 7, 4, 6], [0, 4, 5, 6],
] as const;
const TETRA_EDGES = [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]] as const;

const FACES = [
  { neighbor: [0, 1, 0], normal: [1, 0, 0], corners: [[.48,-.48,-.48],[.48,.48,-.48],[.48,.48,.48],[.48,-.48,.48]] },
  { neighbor: [0,-1, 0], normal: [-1,0,0], corners: [[-.48,-.48,.48],[-.48,.48,.48],[-.48,.48,-.48],[-.48,-.48,-.48]] },
  { neighbor: [-1,0,0], normal: [0,1,0], corners: [[-.48,.48,-.48],[-.48,.48,.48],[.48,.48,.48],[.48,.48,-.48]] },
  { neighbor: [1, 0,0], normal: [0,-1,0], corners: [[-.48,-.48,.48],[-.48,-.48,-.48],[.48,-.48,-.48],[.48,-.48,.48]] },
  { neighbor: [0,0,1], normal: [0,0,1], corners: [[-.48,-.48,.48],[.48,-.48,.48],[.48,.48,.48],[-.48,.48,.48]] },
  { neighbor: [0,0,-1], normal: [0,0,-1], corners: [[.48,-.48,-.48],[-.48,-.48,-.48],[-.48,.48,-.48],[.48,.48,-.48]] },
] as const;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

function rotate(point: Point3, view: ViewState): Point3 {
  const cosY = Math.cos(view.rotationY), sinY = Math.sin(view.rotationY);
  const x = point.x * cosY + point.z * sinY;
  const z = -point.x * sinY + point.z * cosY;
  const cosX = Math.cos(view.rotationX), sinX = Math.sin(view.rotationX);
  return { x, y: point.y * cosX - z * sinX, z: point.y * sinX + z * cosX };
}

function fieldColor(mode: FieldMode, normalized: number, light: number) {
  const value = clamp(normalized, 0, 1);
  if (mode === "density") {
    const hue = 211 - value * 10;
    const luminance = clamp((87 - value * 52) * light, 19, 88);
    return `hsl(${hue} 64% ${luminance}%)`;
  }
  const hue = 225 - value * 225;
  const luminance = clamp((73 - value * 28) * light, 24, 76);
  return `hsl(${hue} 82% ${luminance}%)`;
}


export default function InteractiveVolumeView({
  density,
  field,
  mode,
  viewState,
  onViewStateChange,
  surfaceOnly = false,
}: {
  density: MatlabVolume;
  field: MatlabVolume;
  mode: FieldMode;
  viewState?: ViewState;
  onViewStateChange?: (state: ViewState) => void;
  surfaceOnly?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<ViewState>({ ...(viewState ?? DEFAULT_VIEW) });
  const dragRef = useRef<{ pointerId: number; x: number; y: number } | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("surface");
  const [rows, columns, layers] = density.shape;

  const statistics = useMemo(() => {
    const values: number[] = [];
    let active = 0;
    for (let layer = 0; layer < layers; layer++) {
      for (let column = 0; column < columns; column++) {
        for (let row = 0; row < rows; row++) {
          if (fortranVolumeValue(density, row, column, layer) < ISO_LEVEL) continue;
          active += 1;
          values.push(fortranVolumeValue(field, row, column, layer));
        }
      }
    }
    return {
      active,
      minimum: values.length ? Math.min(...values) : 0,
      maximum: values.length ? Math.max(...values) : 1,
    };
  }, [columns, density, field, layers, rows]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(420, Math.round(rect.width || 720));
    const height = Math.max(260, Math.round(rect.height || 420));
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const gradient = ctx.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "#fbfdff");
    gradient.addColorStop(1, "#eef3f8");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);

    if (!statistics.active) {
      ctx.fillStyle = "#7d8fa3";
      ctx.font = "12px system-ui";
      ctx.textAlign = "center";
      ctx.fillText("当前迭代没有超过 0.5 等值阈值的材料体素", width / 2, height / 2);
      return;
    }

    const view = viewRef.current;
    const span = Math.max(statistics.maximum - statistics.minimum, 1e-12);
    const scale = Math.min(width - 92, height - 46) / (Math.max(rows, columns, layers) * 1.72) * view.zoom;
    const centerX = width * .48, centerY = height * .5;
    const faces: Face[] = [];
    const activeAt = (row: number, column: number, layer: number) =>
      fortranVolumeValue(density, row, column, layer) >= ISO_LEVEL;

    if (viewMode === "cells") {
      for (let layer = 0; layer < layers; layer++) {
        for (let column = 0; column < columns; column++) {
          for (let row = 0; row < rows; row++) {
            if (!activeAt(row, column, layer)) continue;
            const center = {
              x: column - (columns - 1) / 2,
              y: (rows - 1) / 2 - row,
              z: layer - (layers - 1) / 2,
            };
            const value = fortranVolumeValue(field, row, column, layer);
            for (const definition of FACES) {
              const [dr, dc, dl] = definition.neighbor;
              if (activeAt(row + dr, column + dc, layer + dl)) continue;
              const points = definition.corners.map(([x, y, z]) => rotate({
                x: center.x + x, y: center.y + y, z: center.z + z,
              }, view));
              const normal = rotate({ x: definition.normal[0], y: definition.normal[1], z: definition.normal[2] }, view);
              faces.push({
                points, value,
                depth: points.reduce((total, point) => total + point.z, 0) / points.length,
                light: .72 + .28 * Math.max(0, normal.x * .25 + normal.y * .35 + normal.z * .9),
              });
            }
          }
        }
      }
    } else {
      for (let layer = 0; layer < layers - 1; layer++) {
        for (let column = 0; column < columns - 1; column++) {
          for (let row = 0; row < rows - 1; row++) {
            const cube = CUBE_VERTICES.map(([dr, dc, dl]) => ({
              point: {
                x: column + dc - (columns - 1) / 2,
                y: (rows - 1) / 2 - (row + dr),
                z: layer + dl - (layers - 1) / 2,
              },
              density: fortranVolumeValue(density, row + dr, column + dc, layer + dl),
              field: fortranVolumeValue(field, row + dr, column + dc, layer + dl),
            }));
            for (const tetrahedron of CUBE_TETRAHEDRA) {
              const tetra = tetrahedron.map(index => cube[index]);
              const intersections: Array<{ point: Point3; value: number }> = [];
              for (const [leftIndex, rightIndex] of TETRA_EDGES) {
                const left = tetra[leftIndex], right = tetra[rightIndex];
                if ((left.density >= ISO_LEVEL) === (right.density >= ISO_LEVEL)) continue;
                const amount = (ISO_LEVEL - left.density) / (right.density - left.density);
                intersections.push({
                  point: {
                    x: left.point.x + (right.point.x - left.point.x) * amount,
                    y: left.point.y + (right.point.y - left.point.y) * amount,
                    z: left.point.z + (right.point.z - left.point.z) * amount,
                  },
                  value: left.field + (right.field - left.field) * amount,
                });
              }
              if (intersections.length < 3) continue;
              const rotated = intersections.map(item => ({ ...item, point: rotate(item.point, view) }));
              const center = rotated.reduce((total, item) => ({ x: total.x + item.point.x, y: total.y + item.point.y }), { x: 0, y: 0 });
              center.x /= rotated.length; center.y /= rotated.length;
              rotated.sort((left, right) => Math.atan2(left.point.y - center.y, left.point.x - center.x) - Math.atan2(right.point.y - center.y, right.point.x - center.x));
              for (let index = 1; index < rotated.length - 1; index++) {
                const triangle = [rotated[0], rotated[index], rotated[index + 1]];
                const [a, b, c] = triangle.map(item => item.point);
                const ab = { x: b.x - a.x, y: b.y - a.y, z: b.z - a.z };
                const ac = { x: c.x - a.x, y: c.y - a.y, z: c.z - a.z };
                const normal = { x: ab.y * ac.z - ab.z * ac.y, y: ab.z * ac.x - ab.x * ac.z, z: ab.x * ac.y - ab.y * ac.x };
                const length = Math.hypot(normal.x, normal.y, normal.z) || 1;
                faces.push({
                  points: triangle.map(item => item.point),
                  value: triangle.reduce((total, item) => total + item.value, 0) / 3,
                  depth: triangle.reduce((total, item) => total + item.point.z, 0) / 3,
                  light: .68 + .32 * Math.abs((normal.x * .25 + normal.y * .35 + normal.z * .9) / length),
                });
              }
            }
          }
        }
      }
    }
    faces.sort((left, right) => left.depth - right.depth);
    for (const face of faces) {
      const normalized = mode === "density"
        ? clamp(face.value, 0, 1)
        : (face.value - statistics.minimum) / span;
      ctx.beginPath();
      face.points.forEach((point, index) => {
        const x = centerX + point.x * scale;
        const y = centerY - point.y * scale;
        if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      });
      ctx.closePath();
      ctx.fillStyle = fieldColor(mode, normalized, face.light);
      ctx.fill();
      ctx.strokeStyle = "rgba(28, 55, 82, .16)";
      ctx.lineWidth = .55;
      ctx.stroke();
    }

    // Restore a compact XYZ triad in the lower-left canvas corner.
    const axisOrigin = { x: 38, y: height - 32 };
    const axisLength = 24;
    const axisPoint = (point: Point3) => ({ x: axisOrigin.x + point.x * axisLength, y: axisOrigin.y - point.y * axisLength });
    const axes: Array<[Point3, string, string]> = [[{ x: 1, y: 0, z: 0 }, "X", "#d85858"], [{ x: 0, y: 1, z: 0 }, "Y", "#43a36e"], [{ x: 0, y: 0, z: 1 }, "Z", "#397fc5"]];
    ctx.lineWidth = 1.5;
    ctx.font = "11px system-ui";
    ctx.textAlign = "left";
    for (const [vector, label, color] of axes) {
      const end = axisPoint(rotate(vector, view));
      ctx.beginPath(); ctx.moveTo(axisOrigin.x, axisOrigin.y); ctx.lineTo(end.x, end.y); ctx.strokeStyle = color; ctx.stroke();
      ctx.fillStyle = color; ctx.fillText(label, end.x + 3, end.y + 3);
    }

    const legendX = width - 29, legendY = 36, legendHeight = Math.min(160, height - 86);
    const legend = ctx.createLinearGradient(0, legendY + legendHeight, 0, legendY);
    for (let index = 0; index <= 10; index++) {
      const normalized = index / 10;
      legend.addColorStop(normalized, fieldColor(mode, normalized, 1));
    }
    ctx.fillStyle = legend;
    ctx.fillRect(legendX, legendY, 9, legendHeight);
    ctx.strokeStyle = "#aebdca";
    ctx.strokeRect(legendX, legendY, 9, legendHeight);
    ctx.fillStyle = "#61778e";
    ctx.font = "9px system-ui";
    ctx.textAlign = "right";
    ctx.fillText(statistics.maximum.toPrecision(4), legendX - 4, legendY + 7);
    ctx.fillText(statistics.minimum.toPrecision(4), legendX - 4, legendY + legendHeight);

  }, [columns, density, field, layers, mode, rows, statistics, viewMode]);

  useEffect(() => {
    draw();
    if (typeof ResizeObserver === "undefined" || !canvasRef.current) return;
    const observer = new ResizeObserver(draw);
    observer.observe(canvasRef.current);
    return () => observer.disconnect();
  }, [draw]);

  useEffect(() => {
    if (viewState) viewRef.current = { ...viewState };
  }, [viewState?.rotationX, viewState?.rotationY, viewState?.zoom]);

  const updateView = (change: (view: ViewState) => void) => {
    change(viewRef.current);
    onViewStateChange?.({ ...viewRef.current });
    draw();
  };
  const reset = () => {
    viewRef.current = { ...DEFAULT_VIEW };
    onViewStateChange?.({ ...viewRef.current });
    draw();
  };

  return <div ref={rootRef} className="interactive-volume" data-mode={mode}>
    <div className="volume-toolbar">
      {!surfaceOnly ? <div className="volume-view-switch" role="group" aria-label="三维结构显示方式">
        <button type="button" className={viewMode === "surface" ? "active" : ""} aria-pressed={viewMode === "surface"} onClick={() => setViewMode("surface")}>真实曲面</button>
        <button type="button" className={viewMode === "cells" ? "active" : ""} aria-pressed={viewMode === "cells"} onClick={() => setViewMode("cells")}>单元网格</button>
      </div> : null}
      <div className="volume-controls" aria-label="三维视图控制">
        <button type="button" aria-label="缩小三维视图" title="缩小" onClick={() => updateView(view => { view.zoom = clamp(view.zoom / 1.2, .35, 4); })}><ZoomOut size={14}/></button>
        <button type="button" aria-label="放大三维视图" title="放大" onClick={() => updateView(view => { view.zoom = clamp(view.zoom * 1.2, .35, 4); })}><ZoomIn size={14}/></button>
        <button type="button" aria-label="重置三维视角" title="重置视角" onClick={reset}><RotateCcw size={14}/></button>
        <button type="button" aria-label="全屏查看三维视图" title="全屏查看" onClick={() => { const element = rootRef.current; if (!element) return; if (document.fullscreenElement) void document.exitFullscreen(); else void element.requestFullscreen?.(); }}><Maximize2 size={14}/></button>
      </div>
    </div>
    <div className="volume-canvas-frame">
      <canvas
        ref={canvasRef}
        tabIndex={0}
        role="img"
        aria-label={mode === "density" ? "可旋转缩放的三维密度场" : "可旋转缩放的三维 Von Mises 应力场"}
        onPointerDown={event => {
          dragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
          event.currentTarget.setPointerCapture?.(event.pointerId);
        }}
        onPointerMove={event => {
          const drag = dragRef.current;
          if (!drag || drag.pointerId !== event.pointerId) return;
          const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
          drag.x = event.clientX; drag.y = event.clientY;
          updateView(view => { view.rotationY += dx * .012; view.rotationX += dy * .012; });
        }}
        onPointerUp={event => { if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null; event.currentTarget.releasePointerCapture?.(event.pointerId); }}
        onPointerCancel={() => { dragRef.current = null; }}
        onWheel={event => { event.preventDefault(); updateView(view => { view.zoom = clamp(view.zoom * Math.exp(-event.deltaY * .0012), .35, 4); }); }}
        onDoubleClick={reset}
        onKeyDown={event => {
          if (event.key === "r" || event.key === "R" || event.key === "0") reset();
          else if (event.key === "+" || event.key === "=") updateView(view => { view.zoom = clamp(view.zoom * 1.15, .35, 4); });
          else if (event.key === "-") updateView(view => { view.zoom = clamp(view.zoom / 1.15, .35, 4); });
          else if (event.key.startsWith("Arrow")) { event.preventDefault(); updateView(view => { if (event.key === "ArrowLeft") view.rotationY -= .12; if (event.key === "ArrowRight") view.rotationY += .12; if (event.key === "ArrowUp") view.rotationX -= .12; if (event.key === "ArrowDown") view.rotationX += .12; }); }
        }}
      />
    </div>
  </div>;
}




