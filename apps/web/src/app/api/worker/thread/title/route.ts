import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const response = await workerProxyFetch("/thread/title", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) return NextResponse.json({ detail: error.message }, { status: error.status });
    return NextResponse.json({ detail: "Unexpected error while generating a chat title." }, { status: 500 });
  }
}
