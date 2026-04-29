from pathlib import Path
import logging
import os

from repooperator_worker.config import get_settings
from repooperator_worker.schemas import RepoOpenPlanResponse, RepoOpenRequest, RepoOpenResponse
from repooperator_worker.services.active_repository import ActiveRepository, set_active_repository
from repooperator_worker.services.common import get_repo_base_dir, is_git_repository, resolve_project_path
from repooperator_worker.services.git_providers import (
    ProviderGitOptions,
    resolve_provider_git_options,
)
from repooperator_worker.services.provider_service import record_recent_project
from repooperator_worker.services.repo_open_requests import (
    clear_repository_open_request,
    is_repository_open_request_current,
    mark_repository_open_request_current,
)
from repooperator_worker.services.subprocess_utils import run_subprocess

logger = logging.getLogger(__name__)


def plan_repository_open(request: RepoOpenRequest) -> RepoOpenPlanResponse:
    if _is_local_request(request):
        repo_path = Path(request.project_path).expanduser().resolve()
        return RepoOpenPlanResponse(
            project_path=str(repo_path),
            git_provider="local",
            local_repo_path=str(repo_path),
            local_checkout_exists=repo_path.exists(),
            open_mode="local",
            message="RepoOperator will open the selected local workspace.",
        )

    settings = get_settings()
    repo_base_dir = get_repo_base_dir()
    repo_path = _resolve_repo_path(repo_base_dir, request.project_path)
    provider_options = _get_provider_options(request, settings)
    git_provider = request.git_provider or (provider_options.provider if provider_options else "provider")
    checkout_exists = repo_path.exists() and repo_path.is_dir()
    return RepoOpenPlanResponse(
        project_path=request.project_path,
        git_provider=git_provider,
        local_repo_path=str(repo_path),
        local_checkout_exists=checkout_exists,
        open_mode="refresh" if checkout_exists else "clone",
        message=(
            "RepoOperator will refresh the existing local checkout."
            if checkout_exists
            else "RepoOperator will clone this repository into the local workspace."
        ),
    )


def open_repository(request: RepoOpenRequest) -> RepoOpenResponse:
    mark_repository_open_request_current(request.client_request_id)
    try:
        if _is_local_request(request):
            return _open_local_project(request)

        settings = get_settings()
        repo_base_dir = get_repo_base_dir()
        repo_path = _resolve_repo_path(repo_base_dir, request.project_path)
        cloned = False
        provider_options = _get_provider_options(request, settings)
        if not request.branch:
            raise ValueError("branch is required for provider-backed repositories")

        if not repo_path.exists():
            repo_path.parent.mkdir(parents=True, exist_ok=True)
            clone_url = _get_clone_url(request, provider_options)
            _clone_repository(clone_url, repo_path, provider_options, settings)
            cloned = True
        elif not repo_path.is_dir():
            raise ValueError(f"Repository path is not a directory: {repo_path}")

        _ensure_git_repository(repo_path)
        _fetch_repository(repo_path, provider_options, settings)
        _checkout_branch(repo_path=repo_path, branch=request.branch, provider_options=provider_options)

        head_sha = _git_stdout(["git", "rev-parse", "HEAD"], repo_path)
        current_branch = _git_stdout(["git", "branch", "--show-current"], repo_path) or request.branch
        message = "repository cloned and branch checked out" if cloned else "repository fetched and branch checked out"
        record_recent_project(
            project_path=request.project_path,
            git_provider=request.git_provider or provider_options.provider,
            display_name=request.project_path,
            is_git_repo=True,
        )

        response = RepoOpenResponse(
            project_path=request.project_path,
            git_provider=request.git_provider or provider_options.provider,
            local_repo_path=str(repo_path),
            branch=current_branch,
            head_sha=head_sha,
            cloned=cloned,
            is_git_repository=True,
            message=message,
        )
        _set_active_from_response(response, request.client_request_id)
        return response
    finally:
        clear_repository_open_request(request.client_request_id)


def _open_local_project(request: RepoOpenRequest) -> RepoOpenResponse:
    repo_path = resolve_project_path(request.project_path)
    git_repo = is_git_repository(repo_path)

    branch = None
    head_sha = None
    if git_repo:
        if request.branch:
            _checkout_local_branch(repo_path, request.branch)
        branch = _git_stdout(["git", "branch", "--show-current"], repo_path) or request.branch
        head_sha = _git_stdout(["git", "rev-parse", "HEAD"], repo_path) or None

    record_recent_project(
        project_path=str(repo_path),
        git_provider="local",
        display_name=repo_path.name,
        is_git_repo=git_repo,
    )

    response = RepoOpenResponse(
        project_path=str(repo_path),
        git_provider="local",
        local_repo_path=str(repo_path),
        branch=branch,
        head_sha=head_sha,
        cloned=False,
        is_git_repository=git_repo,
        message=(
            "local git project opened"
            if git_repo
            else "local project opened (no git repository detected)"
        ),
    )
    _set_active_from_response(response, request.client_request_id)
    return response


def _set_active_from_response(
    response: RepoOpenResponse,
    client_request_id: str | None = None,
) -> None:
    if not is_repository_open_request_current(client_request_id):
        logger.info(
            "Skipping active repository update for stale open request '%s'",
            client_request_id,
        )
        return
    set_active_repository(
        ActiveRepository(
            git_provider=response.git_provider,
            project_path=response.project_path,
            local_repo_path=response.local_repo_path,
            branch=response.branch,
            head_sha=response.head_sha,
        )
    )


def _resolve_repo_path(repo_base_dir: Path, project_path: str) -> Path:
    repo_path = (repo_base_dir / project_path).resolve()
    try:
        repo_path.relative_to(repo_base_dir)
    except ValueError as exc:
        raise ValueError("Resolved repository path escapes LOCAL_REPO_BASE_DIR") from exc
    return repo_path


def _get_provider_options(
    request: RepoOpenRequest,
    settings,
) -> ProviderGitOptions | None:
    if request.git_provider:
        return resolve_provider_git_options(
            git_provider=request.git_provider,
            project_path=request.project_path,
            settings=settings,
        )
    return None


def _is_local_request(request: RepoOpenRequest) -> bool:
    return request.git_provider == "local" or Path(request.project_path).expanduser().is_absolute()


def _get_clone_url(
    request: RepoOpenRequest,
    provider_options: ProviderGitOptions | None,
) -> str:
    if provider_options is not None:
        return provider_options.clone_url
    if request.git and request.git.clone_url:
        return request.git.clone_url
    raise ValueError(
        "Repository is missing locally and no clone source was provided. "
        "Set git_provider to a configured provider such as 'gitlab' or 'github', use 'local' for a local project path, or provide git.clone_url."
    )


def _clone_repository(
    clone_url: str,
    repo_path: Path,
    provider_options: ProviderGitOptions | None,
    settings,
) -> None:
    result = run_subprocess(
        command=_build_git_command(
            ["clone", clone_url, str(repo_path)],
            provider_options,
        ),
        cwd=repo_path.parent,
        timeout_seconds=settings.git_clone_timeout_seconds,
        env=_build_git_env(provider_options),
    )
    if result.returncode != 0:
        message = _classify_remote_git_failure(
            stderr=result.stderr,
            stdout=result.stdout,
            provider=provider_options.provider if provider_options else None,
        )
        logger.error(
            "git clone failed for project_path='%s': %s",
            repo_path,
            message,
        )
        raise RuntimeError(message)


def _fetch_repository(
    repo_path: Path,
    provider_options: ProviderGitOptions | None,
    settings,
) -> None:
    result = run_subprocess(
        command=_build_git_command(["fetch", "--all", "--prune"], provider_options),
        cwd=repo_path,
        timeout_seconds=settings.git_fetch_timeout_seconds,
        env=_build_git_env(provider_options),
    )
    if result.returncode != 0:
        message = _classify_remote_git_failure(
            stderr=result.stderr,
            stdout=result.stdout,
            provider=provider_options.provider if provider_options else None,
        )
        logger.error(
            "git fetch failed for repo='%s': %s",
            repo_path,
            message,
        )
        raise RuntimeError(message)


def _ensure_git_repository(repo_path: Path) -> None:
    result = run_subprocess(
        command=["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repo_path,
        timeout_seconds=30,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise ValueError(f"Not a git repository: {repo_path}")


def _checkout_branch(
    repo_path: Path,
    branch: str,
    provider_options: ProviderGitOptions | None,
) -> None:
    existing_local = run_subprocess(
        command=["git", "rev-parse", "--verify", branch],
        cwd=repo_path,
        timeout_seconds=30,
    )
    if existing_local.returncode == 0:
        result = run_subprocess(
            command=["git", "checkout", branch],
            cwd=repo_path,
            timeout_seconds=60,
        )
        if result.returncode != 0:
            logger.error(
                "git checkout failed for repo='%s' branch='%s': %s",
                repo_path,
                branch,
                _summarize_git_failure(result.stderr, result.stdout),
            )
            raise RuntimeError(result.stderr.strip() or f"git checkout {branch} failed")
        return

    _verify_remote_branch_exists(repo_path, branch, provider_options)

    existing_remote = run_subprocess(
        command=["git", "show-ref", "--verify", f"refs/remotes/origin/{branch}"],
        cwd=repo_path,
        timeout_seconds=60,
    )
    if existing_remote.returncode == 0:
        result = run_subprocess(
            command=["git", "checkout", "-B", branch, f"origin/{branch}"],
            cwd=repo_path,
            timeout_seconds=60,
        )
        if result.returncode != 0:
            logger.error(
                "git checkout from origin failed for repo='%s' branch='%s': %s",
                repo_path,
                branch,
                _summarize_git_failure(result.stderr, result.stdout),
            )
            raise RuntimeError(result.stderr.strip() or f"git checkout origin/{branch} failed")
        return

    raise ValueError(
        f"Branch '{branch}' was not found locally or on origin for repository {repo_path.name}"
    )


def _checkout_local_branch(repo_path: Path, branch: str) -> None:
    result = run_subprocess(
        command=["git", "rev-parse", "--verify", branch],
        cwd=repo_path,
        timeout_seconds=30,
    )
    if result.returncode != 0:
        raise ValueError(
            f"Branch '{branch}' was not found in local git repository {repo_path.name}"
        )
    checkout_result = run_subprocess(
        command=["git", "checkout", branch],
        cwd=repo_path,
        timeout_seconds=60,
    )
    if checkout_result.returncode != 0:
        logger.error(
            "git checkout failed for local repo='%s' branch='%s': %s",
            repo_path,
            branch,
            _summarize_git_failure(checkout_result.stderr, checkout_result.stdout),
        )
        raise RuntimeError(
            checkout_result.stderr.strip() or f"git checkout {branch} failed for local project"
        )


def _verify_remote_branch_exists(
    repo_path: Path,
    branch: str,
    provider_options: ProviderGitOptions | None,
) -> None:
    result = run_subprocess(
        command=_build_git_command(
            ["ls-remote", "--exit-code", "--heads", "origin", branch],
            provider_options,
        ),
        cwd=repo_path,
        timeout_seconds=60,
        env=_build_git_env(provider_options),
    )
    if result.returncode == 0:
        return
    if result.returncode == 2:
        raise ValueError(
            f"Branch '{branch}' was not found on origin for repository {repo_path.name}"
        )
    logger.error(
        "git ls-remote failed for repo='%s' branch='%s': %s",
        repo_path,
        branch,
        _classify_remote_git_failure(
            stderr=result.stderr,
            stdout=result.stdout,
            provider=provider_options.provider if provider_options else None,
        ),
    )
    raise RuntimeError(
        _classify_remote_git_failure(
            stderr=result.stderr,
            stdout=result.stdout,
            provider=provider_options.provider if provider_options else None,
        )
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


def _build_git_env(provider_options: ProviderGitOptions | None) -> dict[str, str] | None:
    if provider_options is None:
        return None
    return {
        **os.environ,
        **provider_options.env,
    }


def _summarize_git_failure(stderr: str, stdout: str) -> str:
    summary = stderr.strip() or stdout.strip() or "no command output"
    return summary.splitlines()[0]


def _classify_remote_git_failure(
    stderr: str,
    stdout: str,
    provider: str | None,
) -> str:
    summary = _summarize_git_failure(stderr, stdout)
    combined = f"{stderr}\n{stdout}".lower()
    provider_label = provider or "git provider"

    if "could not read username" in combined or "terminal prompts disabled" in combined:
        return (
            f"{provider_label} authentication failed because no usable token was applied for this repository operation. "
            "Confirm the provider token is stored in ~/.repooperator/config.json or provided as an override."
        )
    if "http basic: access denied" in combined or "authentication failed" in combined or "invalid credentials" in combined:
        return (
            f"{provider_label} authentication failed. Confirm the configured token is valid and has access to this repository."
        )
    if "repository not found" in combined or "project not found" in combined:
        return (
            f"{provider_label} repository was not found or the token does not have permission to access it. "
            "Confirm project_path, provider base URL, and repository permissions."
        )
    if "access denied" in combined or "permission denied" in combined or "not allowed" in combined:
        return (
            f"{provider_label} access was denied for this repository. "
            "Confirm the token has permission to clone or fetch the repository."
        )
    return summary


def _git_stdout(command: list[str], repo_path: Path) -> str:
    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{' '.join(command)} failed")
    return result.stdout.strip()
