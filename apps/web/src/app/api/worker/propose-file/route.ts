import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const response = await workerProxyFetch("/agent/propose-file", {
      method: "POST",
      body,
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }

    return NextResponse.json(
      { detail: "Unexpected error while proposing a file edit." },
      { status: 500 },
    );
  }
}
