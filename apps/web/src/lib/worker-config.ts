const DEFAULT_LOCAL_WORKER_BASE_URL = "http://127.0.0.1:8000";

export function getLocalWorkerBaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_LOCAL_WORKER_BASE_URL?.trim() ||
    DEFAULT_LOCAL_WORKER_BASE_URL
  );
}
