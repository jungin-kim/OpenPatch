import { getLocalWorkerBaseUrl } from "@/lib/worker-config";

const DEFAULT_WORKER_PROXY_TIMEOUT_MS = 3000;

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
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    DEFAULT_WORKER_PROXY_TIMEOUT_MS,
  );

  try {
    return await fetch(workerUrl, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new WorkerProxyError(
        `The local worker at ${workerBaseUrl} did not respond in time. Make sure it is running and healthy.`,
        504,
      );
    }

    throw new WorkerProxyError(
      `Unable to reach the local worker at ${workerBaseUrl}. Make sure it is running and reachable from this app.`,
      503,
    );
  } finally {
    clearTimeout(timeout);
  }
}
