import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ runId: string }> },
) {
  try {
    const { runId } = await params;
    const url = new URL(request.url);
    const after = url.searchParams.get("after_sequence") || "0";
    const response = await workerProxyFetch(
      `/agent/runs/${encodeURIComponent(runId)}/events?after_sequence=${encodeURIComponent(after)}`,
      { method: "GET" },
    );
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Unable to load agent run events." }, { status: 500 });
  }
}
