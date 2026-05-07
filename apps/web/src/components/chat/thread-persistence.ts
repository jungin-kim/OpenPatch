export type RepoIdentityLike = {
  git_provider?: string | null;
  project_path?: string | null;
  local_repo_path?: string | null;
  branch?: string | null;
};

export const LEGACY_ACTIVE_THREAD_KEY = "repooperator-active-thread-id";
export const ACTIVE_REPO_IDENTITY_KEY = "repooperator-active-repo-identity";
export const ACTIVE_THREAD_KEY_PREFIX = "repooperator-active-thread:";

export function repoIdentityKey(repo: RepoIdentityLike): string {
  const provider = normalizeStorageSegment(repo.git_provider || "local");
  const rawPath = repo.project_path || repo.local_repo_path || "unknown";
  const normalizedPath = normalizeStorageSegment(normalizeRepoPath(rawPath));
  const branch = normalizeStorageSegment(repo.branch || "default");
  return `${provider}:${normalizedPath}:${branch}`;
}

export function activeThreadStorageKey(repo: RepoIdentityLike): string {
  return activeThreadStorageKeyForIdentity(repoIdentityKey(repo));
}

export function activeThreadStorageKeyForIdentity(identity: string): string {
  return `${ACTIVE_THREAD_KEY_PREFIX}${identity}`;
}

export function repoMatchesIdentity(repo: RepoIdentityLike, identity: string | null | undefined): boolean {
  return Boolean(identity) && repoIdentityKey(repo) === identity;
}

function normalizeRepoPath(path: string): string {
  const normalized = String(path || "")
    .trim()
    .replace(/\\/g, "/")
    .replace(/\/+$/, "");
  return normalized || "unknown";
}

function normalizeStorageSegment(value: string): string {
  return encodeURIComponent(String(value || "unknown").trim() || "unknown");
}
