import { NextResponse } from "next/server";

import { WorkerProxyError } from "@/lib/worker-proxy";
import { getLocalWorkerBaseUrl } from "@/lib/worker-config";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const workerBaseUrl = getLocalWorkerBaseUrl();
  const workerUrl = `${workerBaseUrl}/agent/run/stream`;

  try {
    const body = await request.text();

    const upstreamResponse = await fetch(workerUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    });

    if (!upstreamResponse.ok || !upstreamResponse.body) {
      const text = await upstreamResponse.text().catch(() => "");
      return NextResponse.json(
        { detail: text || "Stream request failed." },
        { status: upstreamResponse.status },
      );
    }

    return new Response(upstreamResponse.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        Connection: "keep-alive",
      },
    });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json(
      { detail: "Unable to reach the local worker for streaming." },
      { status: 503 },
    );
  }
}
