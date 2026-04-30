"use client";

export type PermissionMode = "basic" | "auto_review" | "full_access";
export type LegacyWriteMode = "read-only" | "write-with-approval" | "auto-apply";

export type WorkerHealthPayload = {
  status: string;
  service: string;
  repo_base_dir: string;
  configured_git_provider?: string | null;
  configured_repository_source?: string | null;
  configured_model_connection_mode?: string | null;
  configured_model_provider?: string | null;
  configured_model_name?: string | null;
  configured_model_base_url?: string | null;
  write_mode?: LegacyWriteMode;
  permission_mode?: PermissionMode;
  sandbox_scope?: string;
  approval_policy?: Record<string, boolean>;
  tool_permissions?: Record<string, string>;
  recent_projects?: string[];
};

export type PermissionModePayload = {
  mode: PermissionMode;
  write_mode: LegacyWriteMode;
  available_modes: PermissionMode[];
  unsupported_modes?: PermissionMode[];
  sandbox?: Record<string, boolean | string>;
  approval?: Record<string, boolean>;
  tools?: Record<string, string>;
  profile?: Record<string, unknown>;
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

export type RecentProjectsPayload = {
  projects: ProviderProjectSummary[];
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
  git_provider: string;
  local_repo_path: string;
  branch?: string | null;
  head_sha?: string | null;
  cloned: boolean;
  is_git_repository: boolean;
  message: string;
};

export type RepoOpenPlanPayload = {
  project_path: string;
  git_provider: string;
  local_repo_path: string;
  local_checkout_exists: boolean;
  open_mode: "clone" | "refresh" | "local" | "unknown";
  message: string;
};

export type FileReadPayload = {
  project_path: string;
  relative_path: string;
  content: string;
  truncated: boolean;
  bytes_read: number;
};

export type LocalBranchSummary = {
  name: string;
  is_current: boolean;
};

export type GitBranchListPayload = {
  project_path: string;
  current_branch: string | null;
  branches: LocalBranchSummary[];
};

export type GitBranchCreatePayload = {
  project_path: string;
  branch: string;
  from_ref: string;
  head_sha: string;
  message: string;
};

export type GitCheckoutPayload = {
  project_path: string;
  branch: string;
  head_sha: string | null;
  message: string;
};

export type AgentProposeFilePayload = {
  project_path: string;
  relative_path: string;
  model: string;
  context_summary: string;
  original_content: string;
  proposed_content: string;
};

export type FileWritePayload = {
  project_path: string;
  relative_path: string;
  bytes_written: number;
  message: string;
};

export type AgentRunPayload = {
  project_path: string;
  git_provider?: string | null;
  active_repository_source?: string | null;
  active_repository_path?: string | null;
  active_branch?: string | null;
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
  // Write-intent routing fields
  response_type?: "assistant_answer" | "change_proposal" | "permission_required" | "clarification" | "proposal_error" | "command_approval" | "command_result" | "command_denied" | "command_error";
  proposal_relative_path?: string | null;
  proposal_original_content?: string | null;
  proposal_proposed_content?: string | null;
  proposal_context_summary?: string | null;
  clarification_candidates?: string[];
  selected_target_file?: string | null;
  intent_classification?: string | null;
  graph_path?: string | null;
  agent_flow?: string | null;
  proposal_error_details?: string | null;
  command_approval?: CommandApprovalPayload | null;
  command_result?: CommandResultPayload | null;
  run_id?: string | null;
  skills_used?: string[];
  thread_context_files?: string[];
  thread_context_symbols?: string[];
  context_source?: string | null;
  context_reference_resolver?: string | null;
  resolved_reference_type?: string | null;
  resolved_files?: string[];
  resolved_symbols?: string[];
  reference_confidence?: number | null;
  reference_clarification_needed?: boolean | null;
};

export type CommandApprovalPayload = {
  type: "command_approval";
  approval_id: string;
  command: string[];
  display_command: string;
  cwd?: string | null;
  risk: "low" | "medium" | "high" | string;
  read_only: boolean;
  needs_network: boolean;
  touches_outside_repo: boolean;
  needs_approval: boolean;
  blocked?: boolean;
  reason: string;
  pattern?: string;
  options?: string[];
};

export type CommandResultPayload = CommandApprovalPayload & {
  status: string;
  exit_code: number;
  stdout: string;
  stderr: string;
  duration_ms?: number;
};

export type ThreadMessagePayload = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
  metadata?: AgentRunPayload | Record<string, unknown> | null;
};

export type ThreadRecordPayload = {
  id: string;
  title: string;
  repo: RepoOpenPayload;
  messages: ThreadMessagePayload[];
  created_at: string;
  updated_at: string;
};

export type ThreadListPayload = {
  threads: ThreadRecordPayload[];
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

export async function getPermissionMode(): Promise<PermissionModePayload> {
  const response = await fetch("/api/worker/permissions", { cache: "no-store" });
  return parseWorkerResponse<PermissionModePayload>(response);
}

export async function updatePermissionMode(mode: PermissionMode): Promise<PermissionModePayload> {
  const response = await fetch("/api/worker/permissions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  return parseWorkerResponse<PermissionModePayload>(response);
}

export async function runApprovedCommand(input: {
  command: string[];
  approval_id?: string;
  remember_for_session?: boolean;
  decision?: string;
}): Promise<CommandResultPayload> {
  const response = await fetch("/api/worker/commands/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      argv: input.command,
      approval_id: input.approval_id,
      remember_for_session: input.remember_for_session,
      decision: input.decision,
    }),
  });
  return parseWorkerResponse<CommandResultPayload>(response);
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

export async function getRecentProjects(input: { limit?: number } = {}): Promise<RecentProjectsPayload> {
  const query = new URLSearchParams();
  if (input.limit) {
    query.set("limit", String(input.limit));
  }

  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await fetch(`/api/worker/provider/recent-projects${suffix}`, {
    cache: "no-store",
  });
  return parseWorkerResponse<RecentProjectsPayload>(response);
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
  client_request_id?: string;
}): Promise<RepoOpenPayload> {
  const response = await fetch("/api/worker/repo-open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  return parseWorkerResponse<RepoOpenPayload>(response);
}

export async function getRepositoryOpenPlan(input: {
  project_path: string;
  branch?: string;
  git_provider?: string;
  client_request_id?: string;
}): Promise<RepoOpenPlanPayload> {
  const response = await fetch("/api/worker/repo-open-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  return parseWorkerResponse<RepoOpenPlanPayload>(response);
}

export type ConversationMessage = {
  role: "user" | "assistant" | "system";
  content: string;
  metadata?: Record<string, unknown> | AgentRunPayload | null;
};

export async function runAgentTask(input: {
  project_path: string;
  git_provider?: string;
  branch?: string;
  task: string;
  conversation_history?: ConversationMessage[];
}): Promise<AgentRunPayload> {
  const response = await fetch("/api/worker/agent-run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  return parseWorkerResponse<AgentRunPayload>(response);
}

export type AgentProgressEvent =
  | { type: "progress"; node: string; message: string }
  | { type: "done"; result: AgentRunPayload }
  | { type: "error"; message: string };

export async function* streamAgentTask(input: {
  project_path: string;
  git_provider?: string;
  branch?: string;
  task: string;
  conversation_history?: ConversationMessage[];
}): AsyncGenerator<AgentProgressEvent> {
  const response = await fetch("/api/worker/agent/run/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new LocalWorkerClientError(text || "Stream request failed.", response.status);
  }

  if (!response.body) {
    throw new LocalWorkerClientError("No response body for stream.", 500);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const dataStr = line.slice(6).trim();
        if (dataStr === "[DONE]") return;
        try {
          yield JSON.parse(dataStr) as AgentProgressEvent;
        } catch {
          // skip malformed events
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
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

export async function listLocalBranches(input: {
  project_path: string;
}): Promise<GitBranchListPayload> {
  const query = new URLSearchParams({ project_path: input.project_path });
  const response = await fetch(`/api/worker/git-branches?${query.toString()}`, {
    cache: "no-store",
  });
  return parseWorkerResponse<GitBranchListPayload>(response);
}

export async function createLocalBranch(input: {
  project_path: string;
  branch: string;
  from_ref?: string;
  checkout?: boolean;
}): Promise<GitBranchCreatePayload> {
  const response = await fetch("/api/worker/git-branch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_path: input.project_path,
      branch: input.branch,
      from_ref: input.from_ref ?? "HEAD",
      checkout: input.checkout ?? true,
    }),
  });
  return parseWorkerResponse<GitBranchCreatePayload>(response);
}

export async function checkoutLocalBranch(input: {
  project_path: string;
  branch: string;
}): Promise<GitCheckoutPayload> {
  const response = await fetch("/api/worker/git-checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return parseWorkerResponse<GitCheckoutPayload>(response);
}

export async function proposeFileEdit(input: {
  project_path: string;
  relative_path: string;
  instruction: string;
}): Promise<AgentProposeFilePayload> {
  const response = await fetch("/api/worker/propose-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return parseWorkerResponse<AgentProposeFilePayload>(response);
}

export async function writeRepositoryFile(input: {
  project_path: string;
  relative_path: string;
  content: string;
}): Promise<FileWritePayload> {
  const response = await fetch("/api/worker/fs-write", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return parseWorkerResponse<FileWritePayload>(response);
}

export async function listThreads(): Promise<ThreadListPayload> {
  const response = await fetch("/api/worker/threads", { cache: "no-store" });
  return parseWorkerResponse<ThreadListPayload>(response);
}

export async function saveThread(input: ThreadRecordPayload): Promise<ThreadRecordPayload> {
  const response = await fetch("/api/worker/threads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  return parseWorkerResponse<ThreadRecordPayload>(response);
}
