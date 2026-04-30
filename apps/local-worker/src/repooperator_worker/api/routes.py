import time
import json
from threading import Thread

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

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
from repooperator_worker.services.agent_orchestration_graph import stream_agent_orchestration_graph
from repooperator_worker.services.apply_summary_service import generate_apply_summary
from repooperator_worker.services.command_runner import run_command
from repooperator_worker.services.command_service import (
    list_command_approvals,
    preview_command,
    revoke_command_approval,
    run_command_with_policy,
)
from repooperator_worker.services.file_service import read_text_file, write_text_file
from repooperator_worker.services.provider_service import (
    list_provider_branches,
    list_provider_projects,
    list_recent_projects,
    list_recent_project_paths,
)
from repooperator_worker.services.permissions_service import (
    get_permission_mode,
    permission_profile,
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
from repooperator_worker.services.tool_service import get_tools_status, preview_tool_run, run_tool
from repooperator_worker.services.debug_service import (
    get_debug_runtime_status,
    integration_status,
)
from repooperator_worker.services.composio_service import (
    composio_connection_instructions,
    get_composio_status,
    list_composio_connected_accounts,
    list_composio_toolkits,
)
from repooperator_worker.services.event_service import (
    append_run_event,
    complete_active_run,
    get_active_runs,
    get_run,
    list_run_events,
    new_run_id,
    record_agent_run,
    record_event,
    start_active_run,
)
from repooperator_worker.services.memory_service import (
    list_memory_items,
    maybe_record_from_agent_run,
    record_applied_file_write,
)
from repooperator_worker.services.skills_service import discover_skills

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    profile = permission_profile(settings.permission_mode)
    return HealthResponse(
        status="ok",
        service="repooperator-local-worker",
        repo_base_dir=str(settings.repo_base_dir),
        configured_git_provider=settings.configured_git_provider,
        configured_repository_source=settings.configured_git_provider,
        configured_repository_sources=settings.configured_repository_sources,
        configured_model_connection_mode=settings.configured_model_connection_mode,
        configured_model_provider=settings.configured_model_provider,
        configured_model_name=settings.configured_model_name,
        configured_model_base_url=settings.openai_base_url,
        config_loaded_at=settings.config_loaded_at,
        config_source_path=str(settings.repooperator_config_path),
        config_hash=settings.config_hash,
        write_mode=settings.write_mode,
        permission_mode=profile["mode"],
        sandbox_scope=profile["sandbox"]["scope"],
        approval_policy=profile["approval"],
        tool_permissions=profile["tools"],
        recent_projects=list_recent_project_paths(),
    )


@router.get("/permissions", response_model=PermissionModeResponse)
def permissions_get() -> PermissionModeResponse:
    return get_permission_mode()


@router.post("/admin/reload-config")
def admin_reload_config() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "configured_model_connection_mode": settings.configured_model_connection_mode,
        "configured_model_provider": settings.configured_model_provider,
        "configured_model_name": settings.configured_model_name,
        "configured_model_base_url": settings.openai_base_url,
        "configured_git_provider": settings.configured_git_provider,
        "configured_repository_sources": settings.configured_repository_sources,
        "effective_repository_sources": settings.configured_repository_sources,
        "config_loaded_at": settings.config_loaded_at,
        "config_source_path": str(settings.repooperator_config_path),
        "config_hash": settings.config_hash,
        "api_key_configured": bool(settings.openai_api_key),
    }


@router.post("/permissions", response_model=PermissionModeResponse)
def permissions_post(request: PermissionModeRequest) -> PermissionModeResponse:
    try:
        return update_permission_mode(request.mode or request.write_mode)
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


@router.get("/integrations/composio/status")
def composio_status() -> dict:
    try:
        return get_composio_status()
    except RuntimeError as exc:
        return {
            "provider": "Composio",
            "status": "error",
            "configured": True,
            "message": str(exc),
            "accounts": [],
            "toolkits": [],
            "tools_count": 0,
        }


@router.get("/integrations/composio/toolkits")
def composio_toolkits() -> dict:
    try:
        return list_composio_toolkits()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/integrations/composio/accounts")
def composio_accounts() -> dict:
    try:
        return list_composio_connected_accounts()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/integrations/composio/connect")
def composio_connect() -> dict:
    return composio_connection_instructions()


@router.get("/tools")
def tools_status() -> dict:
    return get_tools_status()


@router.post("/tools/run-preview")
def tools_run_preview(request: dict) -> dict:
    argv = request.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise HTTPException(status_code=400, detail="argv must be a list of strings.")
    preview = preview_tool_run(argv)
    record_event(
        event_type="tool_preview",
        repo=preview.get("cwd"),
        summary=f"Previewed local tool command: {' '.join(argv)}",
        tool=argv[0] if argv else None,
        command=argv,
    )
    return preview


@router.post("/tools/run")
def tools_run(request: dict) -> dict:
    argv = request.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise HTTPException(status_code=400, detail="argv must be a list of strings.")
    try:
        return run_tool(argv, confirmed=bool(request.get("confirmed")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/commands/preview")
def commands_preview(request: dict) -> dict:
    argv = request.get("argv") or request.get("command")
    try:
        return preview_command(argv, reason=request.get("reason"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/commands/run")
def commands_run(request: dict) -> dict:
    argv = request.get("argv") or request.get("command")
    try:
        decision = request.get("decision", "yes")
        record_event(
            event_type="command_approval",
            summary=f"Command approval decision: {decision}",
            command=argv if isinstance(argv, list) else None,
            status="denied" if decision == "no_explain" else "ok",
        )
        if decision == "no_explain":
            return {
                "status": "denied",
                "command": argv,
                "stdout": "",
                "stderr": "",
                "exit_code": None,
                "message": "Command was not run. RepoOperator will explain another approach.",
            }
        return run_command_with_policy(
            argv,
            approval_id=request.get("approval_id"),
            remember_for_session=bool(request.get("remember_for_session")),
            reason=request.get("reason"),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/commands/approvals")
def commands_approvals() -> dict:
    return list_command_approvals()


@router.delete("/commands/approvals/{approval_id}")
def commands_approval_revoke(approval_id: str) -> dict:
    return revoke_command_approval(approval_id)


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
        response = write_text_file(request)
        record_applied_file_write(request)
        return response
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
    run_id = new_run_id()
    start = time.perf_counter()
    response: AgentRunResponse | None = None
    record_event(
        event_type="agent_run_started",
        repo=request.project_path,
        branch=request.branch,
        summary=request.task,
    )
    try:
        response = run_agent_task(request).model_copy(update={"run_id": run_id})
        record_event(
            event_type="agent_classifier",
            repo=request.project_path,
            branch=request.branch,
            status=response.response_type,
            summary=(
                f"classifier={response.classifier or 'unknown'} "
                f"intent={response.intent_classification or 'unknown'} "
                f"confidence={response.classifier_confidence if response.classifier_confidence is not None else 'unknown'}"
            ),
            files=response.resolved_files or response.files_read,
        )
        record_event(
            event_type="agent_validation",
            repo=request.project_path,
            branch=request.branch,
            status=response.validation_status or "unknown",
            summary=response.graph_path or "",
            files=response.files_read,
        )
        for file_path in response.files_read:
            record_event(
                event_type="file_read",
                repo=request.project_path,
                branch=request.branch,
                summary=f"Agent read {file_path}",
                files=[file_path],
            )
        if response.response_type == "change_proposal":
            record_event(
                event_type="proposal",
                repo=request.project_path,
                branch=request.branch,
                summary=response.response,
                files=[response.proposal_relative_path] if response.proposal_relative_path else [],
            )
        if response.response_type == "edit_applied":
            for record in response.edit_archive:
                record_event(
                    event_type="file_edited",
                    repo=request.project_path,
                    branch=request.branch,
                    summary=(
                        f"Edited {record.get('file_path')} "
                        f"+{record.get('additions', 0)} -{record.get('deletions', 0)}"
                    ),
                    files=[record.get("file_path")] if record.get("file_path") else [],
                )
            record_event(
                event_type="final_summary",
                repo=request.project_path,
                branch=request.branch,
                summary=response.response,
                files=[record.get("file_path") for record in response.edit_archive if record.get("file_path")],
            )
        maybe_record_from_agent_run(request, response)
        return response
    except ValueError as exc:
        record_agent_run(
            run_id=run_id,
            request=request,
            response=response,
            status="error",
            latency_ms=int((time.perf_counter() - start) * 1000),
            error=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        record_agent_run(
            run_id=run_id,
            request=request,
            response=response,
            status="error",
            latency_ms=int((time.perf_counter() - start) * 1000),
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if response is not None:
            record_agent_run(
                run_id=run_id,
                request=request,
                response=response,
                status="ok",
                latency_ms=int((time.perf_counter() - start) * 1000),
            )


@router.post("/agent/run/stream")
def agent_run_stream(request: AgentRunRequest) -> StreamingResponse:
    run_id = new_run_id()
    start_active_run(run_id=run_id, request=request)

    def worker() -> None:
        final_result: dict | None = None
        try:
            for event_data in stream_agent_orchestration_graph(request, run_id=run_id):
                try:
                    event = json.loads(event_data)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "final_message":
                    final_result = event.get("result")
                    if isinstance(final_result, dict):
                        final_result = {**final_result, "activity_events": list_run_events(run_id)}
                        event = {**event, "result": final_result}
                append_run_event(run_id, event)
            complete_active_run(run_id=run_id, status="completed", final_result=final_result)
        except Exception as exc:
            append_run_event(run_id, {"type": "error", "message": str(exc), "status": "failed"})
            complete_active_run(run_id=run_id, status="failed", error=str(exc))

    Thread(target=worker, daemon=True).start()

    def generate():
        last_sequence = 0
        while True:
            events = list_run_events(run_id, after_sequence=last_sequence)
            for event in events:
                last_sequence = int(event.get("sequence") or last_sequence)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            run = get_run(run_id)
            if run and run.get("status") != "running" and not events:
                break
            time.sleep(0.25)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/agent/runs/active")
def agent_runs_active(thread_id: str | None = None) -> dict:
    return {"runs": get_active_runs(thread_id=thread_id)}


@router.get("/agent/runs/{run_id}")
def agent_run_lookup(run_id: str) -> dict:
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.get("/agent/runs/{run_id}/events")
def agent_run_events(run_id: str, after_sequence: int = 0) -> dict:
    return {"events": list_run_events(run_id, after_sequence=after_sequence)}


@router.post("/agent/apply-summary")
def agent_apply_summary(payload: dict) -> dict:
    return generate_apply_summary(payload)


@router.post("/agent/propose-file", response_model=AgentProposeFileResponse)
def agent_propose_file(request: AgentProposeFileRequest) -> AgentProposeFileResponse:
    try:
        return propose_file_edit(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
