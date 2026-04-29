from fastapi import APIRouter, HTTPException

from repooperator_worker.config import get_settings
from repooperator_worker.schemas import (
    AgentProposeFileRequest,
    AgentProposeFileResponse,
    AgentRunRequest,
    AgentRunResponse,
    CommandRunRequest,
    CommandRunResponse,
    FileReadRequest,
    FileReadResponse,
    FileWriteRequest,
    FileWriteResponse,
    GitBranchCreateRequest,
    GitBranchCreateResponse,
    GitBranchListRequest,
    GitBranchListResponse,
    GitCheckoutRequest,
    GitCheckoutResponse,
    GitCommitRequest,
    GitCommitResponse,
    GitDiffRequest,
    GitDiffResponse,
    GitMergeRequestCreateRequest,
    GitMergeRequestCreateResponse,
    PermissionModeRequest,
    PermissionModeResponse,
    GitPushRequest,
    GitPushResponse,
    HealthResponse,
    ProviderBranchesResponse,
    ProviderProjectsResponse,
    RecentProjectsResponse,
    RepoOpenPlanResponse,
    RepoOpenRequest,
    RepoOpenResponse,
    ThreadListResponse,
    ThreadSummary,
    ThreadUpsertRequest,
)
from repooperator_worker.services.edit_service import propose_file_edit
from repooperator_worker.services.agent_service import run_agent_task
from repooperator_worker.services.command_runner import run_command
from repooperator_worker.services.file_service import read_text_file, write_text_file
from repooperator_worker.services.provider_service import (
    list_provider_branches,
    list_provider_projects,
    list_recent_projects,
    list_recent_project_paths,
)
from repooperator_worker.services.permissions_service import (
    get_permission_mode,
    update_permission_mode,
)
from repooperator_worker.services.git_service import (
    checkout_branch,
    commit_changes,
    create_branch,
    create_provider_merge_request,
    get_diff,
    list_local_branches,
    push_branch,
)
from repooperator_worker.services.repo_service import open_repository, plan_repository_open
from repooperator_worker.services.thread_service import list_threads, upsert_thread
from repooperator_worker.services.debug_service import (
    discover_skills,
    get_debug_runtime_status,
    integration_status,
    list_memory_items,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="repooperator-local-worker",
        repo_base_dir=str(settings.repo_base_dir),
        configured_git_provider=settings.configured_git_provider,
        configured_repository_source=settings.configured_git_provider,
        configured_model_connection_mode=settings.configured_model_connection_mode,
        configured_model_provider=settings.configured_model_provider,
        configured_model_name=settings.configured_model_name,
        configured_model_base_url=settings.openai_base_url,
        write_mode=settings.write_mode,
        recent_projects=list_recent_project_paths(),
    )


@router.get("/permissions", response_model=PermissionModeResponse)
def permissions_get() -> PermissionModeResponse:
    return get_permission_mode()


@router.post("/permissions", response_model=PermissionModeResponse)
def permissions_post(request: PermissionModeRequest) -> PermissionModeResponse:
    try:
        return update_permission_mode(request.write_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/debug/runtime")
def debug_runtime() -> dict:
    return get_debug_runtime_status()


@router.get("/debug/memory")
def debug_memory() -> dict:
    return list_memory_items()


@router.get("/debug/skills")
def debug_skills() -> dict:
    return discover_skills()


@router.get("/debug/integrations")
def debug_integrations() -> dict:
    return integration_status()


@router.get("/provider/projects", response_model=ProviderProjectsResponse)
def provider_projects(
    git_provider: str,
    search: str | None = None,
) -> ProviderProjectsResponse:
    try:
        return list_provider_projects(git_provider=git_provider, search=search)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/provider/recent-projects", response_model=RecentProjectsResponse)
def provider_recent_projects(limit: int = 20) -> RecentProjectsResponse:
    safe_limit = max(1, min(limit, 50))
    return RecentProjectsResponse(projects=list_recent_projects(limit=safe_limit))


@router.get("/provider/branches", response_model=ProviderBranchesResponse)
def provider_branches(
    git_provider: str,
    project_path: str,
) -> ProviderBranchesResponse:
    try:
        return list_provider_branches(
            git_provider=git_provider,
            project_path=project_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/threads", response_model=ThreadListResponse)
def threads_list() -> ThreadListResponse:
    return list_threads()


@router.post("/threads", response_model=ThreadSummary)
def threads_upsert(request: ThreadUpsertRequest) -> ThreadSummary:
    try:
        return upsert_thread(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/repo/open", response_model=RepoOpenResponse)
def repo_open(request: RepoOpenRequest) -> RepoOpenResponse:
    try:
        return open_repository(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/repo/open-plan", response_model=RepoOpenPlanResponse)
def repo_open_plan(request: RepoOpenRequest) -> RepoOpenPlanResponse:
    try:
        return plan_repository_open(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/fs/read", response_model=FileReadResponse)
def fs_read(request: FileReadRequest) -> FileReadResponse:
    try:
        return read_text_file(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/fs/write", response_model=FileWriteResponse)
def fs_write(request: FileWriteRequest) -> FileWriteResponse:
    try:
        return write_text_file(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cmd/run", response_model=CommandRunResponse)
def cmd_run(request: CommandRunRequest) -> CommandRunResponse:
    try:
        return run_command(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/git/diff", response_model=GitDiffResponse)
def git_diff(request: GitDiffRequest) -> GitDiffResponse:
    try:
        return get_diff(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/git/branches", response_model=GitBranchListResponse)
def git_branches(project_path: str) -> GitBranchListResponse:
    try:
        return list_local_branches(GitBranchListRequest(project_path=project_path))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/git/checkout", response_model=GitCheckoutResponse)
def git_checkout(request: GitCheckoutRequest) -> GitCheckoutResponse:
    try:
        return checkout_branch(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/git/branch", response_model=GitBranchCreateResponse)
def git_branch(request: GitBranchCreateRequest) -> GitBranchCreateResponse:
    try:
        return create_branch(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/git/commit", response_model=GitCommitResponse)
def git_commit(request: GitCommitRequest) -> GitCommitResponse:
    try:
        return commit_changes(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/git/push", response_model=GitPushResponse)
def git_push(request: GitPushRequest) -> GitPushResponse:
    try:
        return push_branch(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/git/merge-request", response_model=GitMergeRequestCreateResponse)
def git_merge_request(
    request: GitMergeRequestCreateRequest,
) -> GitMergeRequestCreateResponse:
    try:
        return create_provider_merge_request(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/agent/run", response_model=AgentRunResponse)
def agent_run(request: AgentRunRequest) -> AgentRunResponse:
    try:
        return run_agent_task(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/agent/propose-file", response_model=AgentProposeFileResponse)
def agent_propose_file(request: AgentProposeFileRequest) -> AgentProposeFileResponse:
    try:
        return propose_file_edit(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
