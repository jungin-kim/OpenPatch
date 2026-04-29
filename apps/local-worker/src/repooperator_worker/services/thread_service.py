import json
import re
from pathlib import Path

from pydantic import ValidationError

from repooperator_worker.schemas import (
    ThreadListResponse,
    ThreadSummary,
    ThreadUpsertRequest,
)
from repooperator_worker.services.common import get_repooperator_home_dir


THREAD_ID_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


def _get_threads_dir() -> Path:
    threads_dir = get_repooperator_home_dir() / "threads"
    threads_dir.mkdir(parents=True, exist_ok=True)
    return threads_dir


def _thread_path(thread_id: str) -> Path:
    safe_id = THREAD_ID_PATTERN.sub("_", thread_id).strip("._-")
    if not safe_id:
        raise ValueError("thread id must contain at least one safe filename character")
    return _get_threads_dir() / f"{safe_id}.json"


def list_threads() -> ThreadListResponse:
    threads: list[ThreadSummary] = []
    for path in _get_threads_dir().glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            threads.append(ThreadSummary(**payload))
        except (OSError, json.JSONDecodeError, ValidationError):
            continue

    threads.sort(key=lambda thread: thread.updated_at, reverse=True)
    return ThreadListResponse(threads=threads)


def upsert_thread(request: ThreadUpsertRequest) -> ThreadSummary:
    thread = ThreadSummary(**request.model_dump())
    path = _thread_path(thread.id)
    if path.exists():
        try:
            existing = ThreadSummary(**json.loads(path.read_text(encoding="utf-8")))
            if existing.updated_at > thread.updated_at:
                return existing
        except (OSError, json.JSONDecodeError, ValidationError):
            pass

    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(thread.model_dump(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp_path.replace(path)
    return thread
