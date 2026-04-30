import { NextResponse } from "next/server";
import { workerProxyFetch } from "@/lib/worker-proxy";

export async function GET() {
  try {
    const response = await workerProxyFetch("/commands/approvals", { method: "GET" });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "Unexpected error while loading command approvals." },
      { status: 500 },
    );
  }
}
