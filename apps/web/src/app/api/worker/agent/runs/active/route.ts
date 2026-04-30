import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const threadId = url.searchParams.get("thread_id");
    const suffix = threadId ? `?thread_id=${encodeURIComponent(threadId)}` : "";
    const response = await workerProxyFetch(`/agent/runs/active${suffix}`, { method: "GET" });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Unable to load active agent runs." }, { status: 500 });
  }
}
