import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const response = await workerProxyFetch("/repo/open", {
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
      { detail: "Unexpected error while opening the repository." },
      { status: 500 },
    );
  }
}
