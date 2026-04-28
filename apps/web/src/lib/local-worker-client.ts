"use client";

export type WorkerHealthPayload = {
  status: string;
  service: string;
  repo_base_dir: string;
  configured_git_provider?: string | null;
  configured_repository_source?: string | null;
  configured_model_connection_mode?: string | null;
  configured_model_provider?: string | null;
  configured_model_name?: string | null;
  recent_projects?: string[];
};

export type ProviderProjectSummary = {
  git_provider: string;
  project_path: string;
  display_name: string;
  default_branch?: string | null;
  source: string;
  is_git_repository?: boolean;
};

export type ProviderProjectsPayload = {
  git_provider: string;
  configured_git_provider?: string | null;
  projects: ProviderProjectSummary[];
  recent_projects: ProviderProjectSummary[];
};

export type ProviderBranchSummary = {
  name: string;
  is_default: boolean;
};

export type ProviderBranchesPayload = {
  git_provider: string;
  project_path: string;
  default_branch?: string | null;
  branches: ProviderBranchSummary[];
};

export type RepoOpenPayload = {
  project_path: string;
  local_repo_path: string;
  branch?: string | null;
  head_sha?: string | null;
  cloned: boolean;
  is_git_repository: boolean;
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
  branch?: string | null;
  repo_root_name: string;
  context_summary: string;
  top_level_entries: string[];
  readme_included: boolean;
  diff_included: boolean;
  is_git_repository: boolean;
  files_read: string[];
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

export async function getProviderProjects(input: {
  git_provider: string;
  search?: string;
}): Promise<ProviderProjectsPayload> {
  const query = new URLSearchParams({
    git_provider: input.git_provider,
  });
  if (input.search?.trim()) {
    query.set("search", input.search.trim());
  }

  const response = await fetch(`/api/worker/provider/projects?${query.toString()}`, {
    cache: "no-store",
  });
  return parseWorkerResponse<ProviderProjectsPayload>(response);
}

export async function getProviderBranches(input: {
  git_provider: string;
  project_path: string;
}): Promise<ProviderBranchesPayload> {
  const query = new URLSearchParams({
    git_provider: input.git_provider,
    project_path: input.project_path,
  });

  const response = await fetch(`/api/worker/provider/branches?${query.toString()}`, {
    cache: "no-store",
  });
  return parseWorkerResponse<ProviderBranchesPayload>(response);
}

export async function openRepository(input: {
  project_path: string;
  branch?: string;
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
