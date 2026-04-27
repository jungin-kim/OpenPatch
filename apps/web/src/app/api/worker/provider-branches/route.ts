import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const response = await workerProxyFetch(
      `/provider/branches?${searchParams.toString()}`,
      {
        method: "GET",
      },
    );
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }

    return NextResponse.json(
      { detail: "Unexpected error while loading available branches." },
      { status: 500 },
    );
  }
}
