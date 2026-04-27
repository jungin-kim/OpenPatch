"use client";

export type WorkerHealthPayload = {
  status: string;
  service: string;
  repo_base_dir: string;
};

export type RepoOpenPayload = {
  project_path: string;
  local_repo_path: string;
  branch: string;
  head_sha: string;
  cloned: boolean;
  message: string;
};

export type FileReadPayload = {
  project_path: string;
  relative_path: string;
  content: string;
  truncated: boolean;
  bytes_read: number;
};

export type AgentRunPayload = {
  project_path: string;
  task: string;
  model: string;
  branch: string;
  repo_root_name: string;
  context_summary: string;
  top_level_entries: string[];
  readme_included: boolean;
  diff_included: boolean;
  response: string;
};

export class LocalWorkerClientError extends Error {
  status: number;

  constructor(message: string, status = 500) {
    super(message);
    this.name = "LocalWorkerClientError";
    this.status = status;
  }
}

async function parseWorkerResponse<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as T & { detail?: string };

  if (!response.ok) {
    throw new LocalWorkerClientError(
      payload.detail || "The local worker request did not complete successfully.",
      response.status,
    );
  }

  return payload;
}

export async function getWorkerHealth(): Promise<WorkerHealthPayload> {
  const response = await fetch("/api/worker/health", { cache: "no-store" });
  return parseWorkerResponse<WorkerHealthPayload>(response);
}

export async function openRepository(input: {
  project_path: string;
  branch: string;
  git_provider?: string;
}): Promise<RepoOpenPayload> {
  const response = await fetch("/api/worker/repo-open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  return parseWorkerResponse<RepoOpenPayload>(response);
}

export async function runAgentTask(input: {
  project_path: string;
  task: string;
}): Promise<AgentRunPayload> {
  const response = await fetch("/api/worker/agent-run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  return parseWorkerResponse<AgentRunPayload>(response);
}

export async function readRepositoryFile(input: {
  project_path: string;
  relative_path: string;
}): Promise<FileReadPayload> {
  const response = await fetch("/api/worker/fs-read", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  return parseWorkerResponse<FileReadPayload>(response);
}
