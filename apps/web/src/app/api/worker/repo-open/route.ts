import { NextResponse } from "next/server";

import {
  WorkerProxyError,
  getDefaultRepoOpenWorkerProxyTimeoutMs,
  workerProxyFetch,
} from "@/lib/worker-proxy";

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const response = await workerProxyFetch("/repo/open", {
      method: "POST",
      body,
      timeoutMs: getDefaultRepoOpenWorkerProxyTimeoutMs(),
      operationName: "repository open",
      timeoutHint:
        "First-time clones can take several minutes, especially for large private repositories. The worker may still be preparing the local checkout; retry Open repository in a moment or check the local worker logs if this repeats.",
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
