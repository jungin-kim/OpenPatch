import { NextResponse } from "next/server";
import { DEFAULT_AGENT_WORKER_PROXY_TIMEOUT_MS, workerProxyFetch } from "@/lib/worker-proxy";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    // Approving a command/network gate resumes the agent loop (model calls),
    // which routinely takes far longer than the default 5s proxy timeout —
    // that abort surfaced as "Unexpected error while running command". Use the
    // agent timeout so the resume can complete.
    const response = await workerProxyFetch("/commands/run", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: DEFAULT_AGENT_WORKER_PROXY_TIMEOUT_MS,
      operationName: "the approval decision",
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "Unexpected error while running command." },
      { status: 500 },
    );
  }
}
