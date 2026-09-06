import type { ConvergencePoint } from "../engineering/artifact-viewer";

const finiteNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

function asMatrix(value: unknown): number[][] | null {
  if (!Array.isArray(value) || !value.length) return null;
  if (value.every(finiteNumber)) return [value];
  if (!value.every(row => Array.isArray(row) && row.length && row.every(finiteNumber))) return null;
  const matrix = value as number[][];
  const width = matrix[0].length;
  return matrix.every(row => row.length === width) ? matrix : null;
}

export function normalizeResearchField(value: unknown): number[][] {
  const matrix = asMatrix(value);
  if (matrix) return matrix;
  if (!Array.isArray(value) || !value.length) return [];
  const layers = value.map(asMatrix);
  if (layers.some(layer => !layer)) return [];
  const valid = layers as number[][][];
  const rows = valid[0].length;
  const columns = valid[0][0].length;
  if (!valid.every(layer => layer.length === rows && layer.every(row => row.length === columns))) return [];
  return Array.from({ length: rows }, (_, row) =>
    Array.from({ length: columns }, (_, column) => Math.max(...valid.map(layer => layer[row][column]))),
  );
}

export function normalizeResearchHistory(value: unknown): ConvergencePoint[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const iteration = finiteNumber(record.iteration) ? record.iteration : index + 1;
    const compliance = finiteNumber(record.compliance)
      ? record.compliance
      : finiteNumber(record.objective) ? record.objective : null;
    return compliance === null ? [] : [{ iteration, compliance }];
  });
}
