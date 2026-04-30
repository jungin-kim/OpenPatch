import { NextResponse } from "next/server";
import { workerProxyFetch } from "@/lib/worker-proxy";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const response = await workerProxyFetch("/commands/preview", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "Unexpected error while previewing command." },
      { status: 500 },
    );
  }
}
