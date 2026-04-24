from openpatch_worker.config import get_settings
from openpatch_worker.schemas import (
    GitBranchCreateRequest,
    GitBranchCreateResponse,
    GitCommitRequest,
    GitCommitResponse,
    GitDiffRequest,
    GitDiffResponse,
    GitMergeRequestCreateRequest,
    GitMergeRequestCreateResponse,
    GitPushRequest,
    GitPushResponse,
)
from openpatch_worker.services.common import ensure_git_repository, resolve_project_path
from openpatch_worker.services.git_providers import ProviderGitOptions, resolve_provider_git_options
from openpatch_worker.services.review_providers import (
    MergeRequestProviderContext,
    create_merge_request,
)
from openpatch_worker.services.subprocess_utils import run_subprocess


def get_diff(request: GitDiffRequest) -> GitDiffResponse:
    repo_path = resolve_project_path(request.project_path)
    ensure_git_repository(repo_path)
    command = ["git", "diff"]

    if request.staged:
        command.append("--cached")

    if request.relative_paths:
        command.append("--")
        command.extend(request.relative_paths)

    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")

    return GitDiffResponse(project_path=request.project_path, diff=result.stdout)


def create_branch(request: GitBranchCreateRequest) -> GitBranchCreateResponse:
    repo_path = resolve_project_path(request.project_path)
    ensure_git_repository(repo_path)

    existing_branch = run_subprocess(
        command=["git", "show-ref", "--verify", f"refs/heads/{request.branch}"],
        cwd=repo_path,
        timeout_seconds=30,
    )
    if existing_branch.returncode == 0:
        raise ValueError(f"Branch '{request.branch}' already exists locally.")

    command = ["git", "checkout", "-b", request.branch, request.from_ref]
    if not request.checkout:
        command = ["git", "branch", request.branch, request.from_ref]

    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Unable to create branch '{request.branch}'")

    head_sha = _git_stdout(["git", "rev-parse", request.branch], repo_path)
    return GitBranchCreateResponse(
        project_path=request.project_path,
        branch=request.branch,
        from_ref=request.from_ref,
        head_sha=head_sha,
        message=(
            f"Created and checked out branch '{request.branch}'"
            if request.checkout
            else f"Created branch '{request.branch}'"
        ),
    )


def commit_changes(request: GitCommitRequest) -> GitCommitResponse:
    repo_path = resolve_project_path(request.project_path)
    ensure_git_repository(repo_path)

    if request.stage_all:
        add_result = run_subprocess(
            command=["git", "add", "--all"],
            cwd=repo_path,
            timeout_seconds=60,
        )
        if add_result.returncode != 0:
            raise RuntimeError(add_result.stderr.strip() or "git add failed")

    status = run_subprocess(
        command=["git", "diff", "--cached", "--quiet"],
        cwd=repo_path,
        timeout_seconds=30,
    )
    if status.returncode == 0:
        raise ValueError("There are no staged changes to commit.")

    result = run_subprocess(
        command=["git", "commit", "-m", request.message],
        cwd=repo_path,
        timeout_seconds=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git commit failed")

    commit_sha = _git_stdout(["git", "rev-parse", "HEAD"], repo_path)
    branch = _git_stdout(["git", "branch", "--show-current"], repo_path) or "HEAD"
    return GitCommitResponse(
        project_path=request.project_path,
        branch=branch,
        commit_sha=commit_sha,
        message=f"Created commit {commit_sha[:8]} on branch '{branch}'",
    )


def push_branch(request: GitPushRequest) -> GitPushResponse:
    repo_path = resolve_project_path(request.project_path)
    ensure_git_repository(repo_path)
    settings = get_settings()
    provider_options = _get_provider_options(request.project_path, request.git_provider, settings)

    command = ["push"]
    if request.set_upstream:
        command.append("--set-upstream")
    command.extend([request.remote, request.branch])

    result = run_subprocess(
        command=_build_git_command(command, provider_options),
        cwd=repo_path,
        timeout_seconds=settings.git_push_timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(_summarize_remote_failure(result.stderr, result.stdout))

    return GitPushResponse(
        project_path=request.project_path,
        remote=request.remote,
        branch=request.branch,
        message=f"Pushed branch '{request.branch}' to remote '{request.remote}'",
    )


def create_provider_merge_request(
    request: GitMergeRequestCreateRequest,
) -> GitMergeRequestCreateResponse:
    return create_merge_request(
        request,
        MergeRequestProviderContext(settings=get_settings()),
    )


def _get_provider_options(
    project_path: str,
    git_provider: str | None,
    settings,
) -> ProviderGitOptions | None:
    if git_provider is None:
        return None
    return resolve_provider_git_options(
        git_provider=git_provider,
        project_path=project_path,
        settings=settings,
    )


def _build_git_command(
    git_args: list[str],
    provider_options: ProviderGitOptions | None,
) -> list[str]:
    command = ["git"]
    if provider_options is not None:
        command.extend(provider_options.git_config_args)
    command.extend(git_args)
    return command


def _summarize_remote_failure(stderr: str, stdout: str) -> str:
    summary = stderr.strip() or stdout.strip() or "remote git operation failed"
    if "authentication" in summary.lower() or "access denied" in summary.lower():
        return f"Authentication failed while contacting the remote: {summary}"
    return summary.splitlines()[0]


def _git_stdout(command: list[str], repo_path) -> str:
    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{' '.join(command)} failed")
    return result.stdout.strip()
