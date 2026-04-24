import os
import subprocess

from openpatch_worker.config import get_settings
from openpatch_worker.schemas import CommandRunRequest, CommandRunResponse
from openpatch_worker.services.common import ensure_git_repository, resolve_project_path
from openpatch_worker.services.subprocess_utils import run_subprocess


def run_command(request: CommandRunRequest) -> CommandRunResponse:
    repo_path = resolve_project_path(request.project_path)
    ensure_git_repository(repo_path)
    timeout_seconds = request.timeout_seconds or get_settings().default_command_timeout_seconds

    try:
        result = run_subprocess(
            command=["sh", "-lc", request.command],
            cwd=repo_path,
            timeout_seconds=timeout_seconds,
            env=os.environ.copy(),
        )
        return CommandRunResponse(
            project_path=request.project_path,
            command=request.command,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"")
        stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"")
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandRunResponse(
            project_path=request.project_path,
            command=request.command,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
