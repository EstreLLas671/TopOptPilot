export interface ConvergencePoint {
  iteration: number;
  compliance: number;
}

export interface TerminalMergeResult {
  lines: string[];
  seenIds: Set<number>;
}

export function parseDensityCsv(text: string): number[][] {
  const rows = text.trim().split(/\r?\n/).filter(Boolean).map(row => row.split(",").map(Number));
  if (!rows.length) return [];
  const width = rows[0].length;
  if (!width || rows.some(row => row.length !== width)) throw new Error("Density CSV must be rectangular");
  if (rows.some(row => row.some(value => !Number.isFinite(value)))) throw new Error("Density CSV values must be finite");
  return rows;
}

export function parseHistoryJson(text: string): ConvergencePoint[] {
  const value: unknown = JSON.parse(text);
  if (!Array.isArray(value)) throw new Error("History artifact must be an array");
  return value.flatMap(item => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const iteration = Number(record.iteration);
    const compliance = Number(record.compliance);
    return Number.isFinite(iteration) && Number.isFinite(compliance) ? [{ iteration, compliance }] : [];
  });
}

export function mergeTerminalResults(previous: string[], seenIds: Set<number>, results: Array<Record<string, unknown>>): TerminalMergeResult {
  const nextSeen = new Set(seenIds);
  let nextLines = previous;
  for (const result of results) {
    const id = Number(result.id);
    if (!Number.isFinite(id) || nextSeen.has(id)) continue;
    nextSeen.add(id);
    if (nextLines === previous) nextLines = [...previous];
    const error = typeof result.error === "string" ? result.error : "";
    const output = typeof result.output === "string" ? result.output : "";
    nextLines.push(error ? `[${String(result.status || "failed")}] ${error}` : output || `[${String(result.status || "completed")}]`);
  }
  return { lines: nextLines, seenIds: nextSeen };
}
