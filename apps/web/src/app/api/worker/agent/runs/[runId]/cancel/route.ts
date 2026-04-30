import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export const dynamic = "force-dynamic";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ runId: string }> },
) {
  try {
    const { runId } = await params;
    const response = await workerProxyFetch(`/agent/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Unable to cancel agent run." }, { status: 500 });
  }
}
