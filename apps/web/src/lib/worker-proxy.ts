import { getLocalWorkerBaseUrl } from "@/lib/worker-config";

const DEFAULT_WORKER_PROXY_TIMEOUT_MS = Number.parseInt(
  process.env.REPOOPERATOR_WORKER_PROXY_TIMEOUT_MS || "5000",
  10,
);
const DEFAULT_AGENT_WORKER_PROXY_TIMEOUT_MS = Number.parseInt(
  process.env.REPOOPERATOR_WORKER_PROXY_AGENT_TIMEOUT_MS || "180000",
  10,
);
const DEFAULT_REPO_OPEN_WORKER_PROXY_TIMEOUT_MS = Number.parseInt(
  process.env.REPOOPERATOR_WORKER_PROXY_REPO_OPEN_TIMEOUT_MS || "600000",
  10,
);

export class WorkerProxyError extends Error {
  status: number;

  constructor(message: string, status = 500) {
    super(message);
    this.name = "WorkerProxyError";
    this.status = status;
  }
}

type WorkerProxyFetchOptions = RequestInit & {
  timeoutMs?: number;
  operationName?: string;
  timeoutHint?: string;
};

export async function workerProxyFetch(
  path: string,
  init?: WorkerProxyFetchOptions,
): Promise<Response> {
  const workerBaseUrl = getLocalWorkerBaseUrl();
  const workerUrl = `${workerBaseUrl}${path}`;
  const controller = new AbortController();
  const timeoutMs = init?.timeoutMs ?? DEFAULT_WORKER_PROXY_TIMEOUT_MS;
  const operationName = init?.operationName || "request";
  const timeoutHint =
    init?.timeoutHint ||
    "Make sure the local worker is running and reachable from this app.";
  const timeout = setTimeout(
    () => controller.abort(),
    timeoutMs,
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
        `The local worker at ${workerBaseUrl} timed out while handling ${operationName}. Wait a bit longer or retry. ${timeoutHint}`,
        504,
      );
    }

    throw new WorkerProxyError(
      `Unable to reach the local worker at ${workerBaseUrl}. Make sure it is running, healthy, and reachable from this app.`,
      503,
    );
  } finally {
    clearTimeout(timeout);
  }
}

export function getDefaultAgentWorkerProxyTimeoutMs(): number {
  return DEFAULT_AGENT_WORKER_PROXY_TIMEOUT_MS;
}

export function getDefaultRepoOpenWorkerProxyTimeoutMs(): number {
  return DEFAULT_REPO_OPEN_WORKER_PROXY_TIMEOUT_MS;
}
