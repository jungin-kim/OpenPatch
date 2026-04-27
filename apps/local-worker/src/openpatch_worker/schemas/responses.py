from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    repo_base_dir: str
    configured_git_provider: str | None = None
    recent_projects: list[str] = []


class ProviderProjectSummary(BaseModel):
    git_provider: str
    project_path: str
    display_name: str
    default_branch: str | None = None
    source: str


class ProviderProjectsResponse(BaseModel):
    git_provider: str
    configured_git_provider: str | None = None
    projects: list[ProviderProjectSummary]
    recent_projects: list[ProviderProjectSummary]


class ProviderBranchSummary(BaseModel):
    name: str
    is_default: bool = False


class ProviderBranchesResponse(BaseModel):
    git_provider: str
    project_path: str
    default_branch: str | None = None
    branches: list[ProviderBranchSummary]


class RepoOpenResponse(BaseModel):
    project_path: str
    local_repo_path: str
    branch: str
    head_sha: str
    cloned: bool
    message: str


class FileReadResponse(BaseModel):
    project_path: str
    relative_path: str
    content: str
    truncated: bool
    bytes_read: int


class FileWriteResponse(BaseModel):
    project_path: str
    relative_path: str
    bytes_written: int
    message: str


class CommandRunResponse(BaseModel):
    project_path: str
    command: str
    timeout_seconds: int
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class GitDiffResponse(BaseModel):
    project_path: str
    diff: str


class GitBranchCreateResponse(BaseModel):
    project_path: str
    branch: str
    from_ref: str
    head_sha: str
    message: str


class GitCommitResponse(BaseModel):
    project_path: str
    branch: str
    commit_sha: str
    message: str


class GitPushResponse(BaseModel):
    project_path: str
    remote: str
    branch: str
    message: str


class GitMergeRequestCreateResponse(BaseModel):
    project_path: str
    git_provider: str
    title: str
    web_url: str
    iid: str
    state: str


class AgentRunResponse(BaseModel):
    project_path: str
    task: str
    model: str
    branch: str
    repo_root_name: str
    context_summary: str
    top_level_entries: list[str]
    readme_included: bool
    diff_included: bool
    response: str


class AgentProposeFileResponse(BaseModel):
    project_path: str
    relative_path: str
    model: str
    context_summary: str
    original_content: str
    proposed_content: str
