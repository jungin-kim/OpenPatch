import { NextResponse } from "next/server";

import { WorkerProxyError, workerProxyFetch } from "@/lib/worker-proxy";

async function forward(request: Request, params: Promise<{ path: string[] }>, method: string) {
  try {
    const { path } = await params;
    const target = `/mcp/${path.map(encodeURIComponent).join("/")}`;
    const body = method === "GET" || method === "DELETE" ? undefined : await request.text();
    const response = await workerProxyFetch(target, { method, body });
    return NextResponse.json(await response.json(), { status: response.status });
  } catch (error) {
    if (error instanceof WorkerProxyError) return NextResponse.json({ detail: error.message }, { status: error.status });
    return NextResponse.json({ detail: "Unexpected error while talking to the MCP endpoint." }, { status: 500 });
  }
}

export async function GET(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, ctx.params, "GET");
}

export async function POST(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, ctx.params, "POST");
}

export async function DELETE(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, ctx.params, "DELETE");
}
