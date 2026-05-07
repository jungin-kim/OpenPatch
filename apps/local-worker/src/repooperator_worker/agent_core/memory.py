from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from repooperator_worker.services.json_safe import json_safe


class MemoryType(str, Enum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


@dataclass
class MemoryRecord:
    id: str
    type: MemoryType
    title: str
    content: str
    why: str
    how_to_apply: str
    source: str
    created_at: str
    updated_at: str
    metadata: dict = field(default_factory=dict)

    def model_dump(self) -> dict:
        return json_safe(self)


class MemoryStore(Protocol):
    def load_project_memory(self, project_path: str) -> list[MemoryRecord]:
        ...

    def save_memory(self, record: MemoryRecord) -> MemoryRecord:
        ...

    def search_memory(self, query: str) -> list[MemoryRecord]:
        ...

    def memory_context_packet(self, project_path: str, query: str | None = None) -> dict:
        ...


class NoOpMemoryStore:
    """Disabled-by-default memory seam.

    Future memory must not store repo facts already present in files, code
    patterns, generated artifacts, or git history; those belong in context.
    """

    def load_project_memory(self, project_path: str) -> list[MemoryRecord]:
        return []

    def save_memory(self, record: MemoryRecord) -> MemoryRecord:
        return record

    def search_memory(self, query: str) -> list[MemoryRecord]:
        return []

    def memory_context_packet(self, project_path: str, query: str | None = None) -> dict:
        return {"enabled": False, "project_path": project_path, "query": query, "records": []}


def new_memory_record(
    *,
    id: str,
    type: MemoryType,
    title: str,
    content: str,
    why: str,
    how_to_apply: str,
    source: str,
) -> MemoryRecord:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return MemoryRecord(
        id=id,
        type=type,
        title=title,
        content=content,
        why=why,
        how_to_apply=how_to_apply,
        source=source,
        created_at=now,
        updated_at=now,
    )
