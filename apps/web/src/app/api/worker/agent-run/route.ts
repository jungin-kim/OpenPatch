import { NextResponse } from "next/server";

import {
  WorkerProxyError,
  getDefaultAgentWorkerProxyTimeoutMs,
  workerProxyFetch,
} from "@/lib/worker-proxy";

export async function POST(request: Request) {
  try {
    const body = await request.text();
    const response = await workerProxyFetch("/agent/run", {
      method: "POST",
      body,
      timeoutMs: getDefaultAgentWorkerProxyTimeoutMs(),
      operationName: "a repository question",
      timeoutHint:
        "Local model inference can take tens of seconds, especially with Ollama. If this keeps happening, confirm the worker is healthy and the configured model runtime or remote API is responsive.",
    });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "application/json",
      },
    });
  } catch (error) {
    if (error instanceof WorkerProxyError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }

    return NextResponse.json(
      { detail: "Unexpected error while running the agent task." },
      { status: 500 },
    );
  }
}
