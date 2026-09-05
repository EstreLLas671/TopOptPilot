import { DEMO_EDITION, initializeBackend } from "./api";

function artifactPath(relativePath: string): string {
  return relativePath.split("/").map(encodeURIComponent).join("/");
}

export async function engineeringArtifactText(runId: string, relativePath: string): Promise<string> {
  const backend = await initializeBackend();
  const response = await fetch(
    `http://127.0.0.1:${backend.port}${DEMO_EDITION ? "/api/demo/four-round/engineering" : "/api/engineering"}/runs/${encodeURIComponent(runId)}/files/${artifactPath(relativePath)}`,
    { headers: { "X-TopOptPilot-Token": backend.token } },
  );
  if (!response.ok) throw new Error(`读取制品失败：${response.status} ${response.statusText}`);
  return response.text();
}
