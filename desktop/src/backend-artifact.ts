import { DEMO_EDITION, initializeBackend } from "./api";

function artifactUrl(port: number, runId: string, relativePath: string): string {
  const safePath = relativePath.split("/").map(encodeURIComponent).join("/");
  const prefix = DEMO_EDITION ? "/api/demo/four-round/engineering" : "/api/engineering";
  return `http://127.0.0.1:${port}${prefix}/runs/${encodeURIComponent(runId)}/files/${safePath}`;
}

async function responseFor(runId: string, relativePath: string): Promise<Response> {
  const backend = await initializeBackend();
  const response = await fetch(artifactUrl(backend.port, runId, relativePath), { headers: { "X-TopOptPilot-Token": backend.token } });
  if (!response.ok) throw new Error(`读取制品失败：${response.status} ${response.statusText}`);
  return response;
}

export async function engineeringArtifactBuffer(runId: string, relativePath: string): Promise<ArrayBuffer> {
  return (await responseFor(runId, relativePath)).arrayBuffer();
}
