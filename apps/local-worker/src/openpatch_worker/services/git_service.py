from openpatch_worker.schemas import GitDiffRequest, GitDiffResponse
from openpatch_worker.services.common import ensure_git_repository, resolve_project_path
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
