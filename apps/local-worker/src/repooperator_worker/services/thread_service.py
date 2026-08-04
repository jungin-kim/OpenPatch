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


# Non-thread JSON files that also live in the threads directory and must be
# skipped by the thread listing (they are not ThreadSummary documents).
_NON_THREAD_JSON = {"queue.json"}


def _is_thread_file(path: Path) -> bool:
    name = path.name
    if name in _NON_THREAD_JSON:
        return False
    # thread context sidecars are stored as "<id>.context.json"
    if name.endswith(".context.json"):
        return False
    return True


def list_threads() -> ThreadListResponse:
    threads: list[ThreadSummary] = []
    for path in _get_threads_dir().glob("*.json"):
        if not _is_thread_file(path):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                # A non-object JSON doc (e.g. a stray list) is not a thread.
                continue
            threads.append(ThreadSummary(**payload))
        except (OSError, json.JSONDecodeError, ValidationError, TypeError):
            continue

    threads.sort(key=lambda thread: thread.updated_at, reverse=True)
    return ThreadListResponse(threads=threads)


def generate_thread_title(task: str, answer: str = "") -> str:
    """Generate a concise chat title from the work (Codex / Claude Code style).

    Returns a short title, or "" on any failure so the caller can fall back to a
    heuristic. Uses the configured model via a single short completion.
    """

    task = (task or "").strip()
    if not task:
        return ""
    from repooperator_worker.services.model_client import (
        ModelGenerationRequest,
        build_model_client,
        split_visible_reasoning,
    )

    prompt = ModelGenerationRequest(
        system_prompt=(
            "You name chat sessions. Given the user's request (and optionally the assistant's answer), "
            "return a concise title of 3 to 6 words that captures the task. Use the same language as the "
            "request. No surrounding quotes, no trailing punctuation, no prefix like 'Title:'. "
            "Return ONLY the title text."
        ),
        user_prompt=json.dumps({"request": task[:2000], "answer": (answer or "")[:800]}, ensure_ascii=False),
    )
    try:
        raw = build_model_client().generate_text(prompt)
    except Exception:
        return ""
    _reasoning, visible = split_visible_reasoning(raw or "")
    title = (visible or raw or "").strip()
    # Take the first non-empty line and strip common wrappers.
    for line in title.splitlines():
        line = line.strip().strip("\"'").removeprefix("Title:").removeprefix("제목:").strip()
        if line:
            return line[:60]
    return ""


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
