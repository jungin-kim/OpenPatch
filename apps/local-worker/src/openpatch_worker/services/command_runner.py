import os
import subprocess

from openpatch_worker.models import CommandRunRequest, CommandRunResponse
from openpatch_worker.services.common import resolve_repo_path
from openpatch_worker.services.subprocess_utils import run_subprocess


def run_command(request: CommandRunRequest) -> CommandRunResponse:
    repo_path = resolve_repo_path(request.repo_path)

    environment = os.environ.copy()
    if request.env:
        # TODO: Add an approval or policy layer before allowing arbitrary env overrides.
        environment.update(request.env)

    try:
        result = run_subprocess(
            command=request.command,
            cwd=repo_path,
            timeout_seconds=request.timeout_seconds,
            env=environment,
        )
        return CommandRunResponse(
            repo_path=str(repo_path),
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
            repo_path=str(repo_path),
            command=request.command,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
