from repooperator_worker.config import get_settings
from repooperator_worker.schemas import CommandRunRequest, CommandRunResponse
from repooperator_worker.services.command_service import run_command_with_policy


def run_command(request: CommandRunRequest) -> CommandRunResponse:
    """Deprecated compatibility adapter.

    Public routes must use ``command_service`` directly. This adapter remains
    only for older internal imports and still enforces the same command policy.
    """
    timeout_seconds = request.timeout_seconds or get_settings().default_command_timeout_seconds
    result = run_command_with_policy(
        request.command,
        approval_id=request.approval_id,
        remember_for_session=request.remember_for_session,
        project_path=request.project_path,
        reason="Compatibility command adapter. Commands still use RepoOperator command approval policy.",
    )
    return CommandRunResponse(
        project_path=request.project_path,
        command=result.get("display_command") or request.command,
        timeout_seconds=timeout_seconds,
        exit_code=result.get("exit_code"),
        stdout=result.get("stdout", ""),
        stderr=result.get("stderr", ""),
        timed_out=False,
    )
