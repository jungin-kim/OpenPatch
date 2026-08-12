import { NextResponse } from "next/server";

import { DEFAULT_AGENT_WORKER_PROXY_TIMEOUT_MS, WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ runId: string }> },
) {
  try {
    const { runId } = await params;
    const body = await request.json();
    const response = await workerProxyFetch(`/agent/runs/${encodeURIComponent(runId)}/change-set/apply`, {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: DEFAULT_AGENT_WORKER_PROXY_TIMEOUT_MS,
      operationName: "applying the change set",
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Unable to apply change set." }, { status: 500 });
  }
}
