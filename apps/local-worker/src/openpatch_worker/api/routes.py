from fastapi import APIRouter, HTTPException

from openpatch_worker.models import (
    CommandRunRequest,
    CommandRunResponse,
    FileReadRequest,
    FileReadResponse,
    GitDiffRequest,
    GitDiffResponse,
    HealthResponse,
    RepoOpenRequest,
    RepoOpenResponse,
)
from openpatch_worker.services.command_runner import run_command
from openpatch_worker.services.file_service import read_text_file
from openpatch_worker.services.git_service import get_diff
from openpatch_worker.services.repo_service import open_repository

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="openpatch-local-worker")


@router.post("/repo/open", response_model=RepoOpenResponse)
def repo_open(request: RepoOpenRequest) -> RepoOpenResponse:
    try:
        return open_repository(request)
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
