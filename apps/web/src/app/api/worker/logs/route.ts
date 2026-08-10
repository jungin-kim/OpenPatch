import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const target = searchParams.get("target") || "worker";
  const lines = searchParams.get("lines") || "200";
  try {
    const response = await workerProxyFetch(`/logs?target=${encodeURIComponent(target)}&lines=${encodeURIComponent(lines)}`, { method: "GET" });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Unexpected error while loading logs." }, { status: 500 });
  }
}
