from openpatch_worker.models import GitDiffRequest, GitDiffResponse
from openpatch_worker.services.common import resolve_repo_path
from openpatch_worker.services.subprocess_utils import run_subprocess


def get_diff(request: GitDiffRequest) -> GitDiffResponse:
    repo_path = resolve_repo_path(request.repo_path)
    command = ["git", "diff"]

    if request.staged:
        command.append("--cached")

    if request.base_ref:
        command.append(request.base_ref)

    if request.paths:
        command.append("--")
        command.extend(request.paths)

    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")

    return GitDiffResponse(repo_path=str(repo_path), diff=result.stdout)
