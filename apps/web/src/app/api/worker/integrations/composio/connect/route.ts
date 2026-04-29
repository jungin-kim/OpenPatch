import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

export async function POST() {
  try {
    const response = await workerProxyFetch("/integrations/composio/connect", { method: "POST" });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) return NextResponse.json({ detail: error.message }, { status: error.status });
    return NextResponse.json({ detail: "Unexpected error while preparing Composio connection setup." }, { status: 500 });
  }
}
