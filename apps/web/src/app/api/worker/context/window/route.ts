import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const qs = searchParams.toString();
    const response = await workerProxyFetch(`/context/window${qs ? `?${qs}` : ""}`, { method: "GET" });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) return NextResponse.json({ detail: error.message }, { status: error.status });
    return NextResponse.json({ detail: "Unexpected error while loading context window snapshot." }, { status: 500 });
  }
}
