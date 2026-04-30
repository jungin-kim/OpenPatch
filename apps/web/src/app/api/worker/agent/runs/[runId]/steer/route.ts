import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ runId: string }> },
) {
  try {
    const { runId } = await params;
    const body = await request.json();
    const response = await workerProxyFetch(`/agent/runs/${encodeURIComponent(runId)}/steer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Unable to steer agent run." }, { status: 500 });
  }
}
