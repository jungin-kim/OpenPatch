import { getLocalWorkerBaseUrl } from "@/lib/worker-config";

export class WorkerProxyError extends Error {
  status: number;

  constructor(message: string, status = 500) {
    super(message);
    this.name = "WorkerProxyError";
    this.status = status;
  }
}

export async function workerProxyFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const workerBaseUrl = getLocalWorkerBaseUrl();
  const workerUrl = `${workerBaseUrl}${path}`;

  try {
    return await fetch(workerUrl, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new WorkerProxyError(
      `Unable to reach the local worker at ${workerBaseUrl}. Make sure it is running and reachable from this app.`,
      503,
    );
  }
}
