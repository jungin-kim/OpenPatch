import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function GET() {
  try {
    const response = await workerProxyFetch("/threads", { method: "GET" });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }

    return NextResponse.json(
      { detail: "Unexpected error while loading thread history." },
      { status: 500 },
    );
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const response = await workerProxyFetch("/threads", {
      method: "POST",
      body,
      operationName: "thread history persistence",
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }

    return NextResponse.json(
      { detail: "Unexpected error while saving thread history." },
      { status: 500 },
    );
  }
}
