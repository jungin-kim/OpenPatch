import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function POST(request: Request) {
  try {
    const response = await workerProxyFetch("/tools/run-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(await request.json()),
    });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) return NextResponse.json({ detail: error.message }, { status: error.status });
    return NextResponse.json({ detail: "Unexpected error while previewing local tool command." }, { status: 500 });
  }
}
