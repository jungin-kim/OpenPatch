import { NextResponse } from "next/server";
import { workerProxyFetch } from "@/lib/worker-proxy";

export async function DELETE(
  _request: Request,
  { params }: { params: Promise<{ approvalId: string }> },
) {
  try {
    const { approvalId } = await params;
    const response = await workerProxyFetch(`/commands/approvals/${encodeURIComponent(approvalId)}`, {
      method: "DELETE",
    });
    const payload = await response.json();
    return NextResponse.json(payload, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "Unexpected error while revoking command approval." },
      { status: 500 },
    );
  }
}
