"""Persistent, incrementally-updated codebase index.

Public entry point: ``get_index(repo)`` returns a process-cached ``CodebaseIndex``
for the repo. The index is built lazily on first use and kept fresh with cheap
(size, mtime) diffing before each query; it is fully offline (no network, no
model calls). All operations on a given repo are serialized by a per-index lock.
"""
from __future__ import annotations

import hashlib
import logging
import threading
from pathlib import Path
from typing import Any

from . import builder, query, store

logger = logging.getLogger(__name__)

_HANDLES: dict[str, "CodebaseIndex"] = {}
_HANDLES_LOCK = threading.Lock()


def _repo_hash(repo: Path) -> str:
    return hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:16]


def _index_db_path(repo: Path) -> Path:
    from repooperator_worker.services.common import get_repooperator_home_dir

    return get_repooperator_home_dir() / "index" / _repo_hash(repo) / "index.db"


class CodebaseIndex:
    def __init__(self, repo: Path) -> None:
        self.repo = repo.resolve()
        self.db_path = _index_db_path(self.repo)
        self._conn = store.connect(self.db_path)
        self._lock = threading.Lock()

    # ── freshness ────────────────────────────────────────────────────────────
    def _ensure_ready(self) -> None:
        """Build once (or on schema change), else reconcile stale files. Best-effort."""
        try:
            if not store.schema_matches(self._conn) or store.get_meta(self._conn, "built_at_ns") is None:
                builder.build(self._conn, self.repo)
            else:
                builder.refresh_stale(self._conn, self.repo)
        except Exception:  # index must never break the caller
            logger.exception("codebase index refresh failed for %s", self.repo)

    def rebuild(self) -> dict:
        with self._lock:
            return builder.build(self._conn, self.repo)

    # ── query API (byte-compatible shapes) ───────────────────────────────────
    def search_files(self, queries: list[str], *, text_queries: list[str] | None = None, max_results: int = 8) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_ready()
            return query.search_files(self._conn, queries, text_queries=text_queries, max_results=max_results)

    def lookup_symbol(self, name: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_ready()
            return query.lookup_symbol(self._conn, name)

    def search_text(
        self,
        *,
        query: str,
        path_globs: list[str],
        max_results: int,
        case_sensitive: bool,
        regex: bool,
        context_lines: int,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        # local import name clash guard: module is imported as ``query`` above
        from . import query as query_mod

        with self._lock:
            self._ensure_ready()
            return query_mod.search_text(
                self._conn,
                self.repo,
                query=query,
                path_globs=path_globs,
                max_results=max_results,
                case_sensitive=case_sensitive,
                regex=regex,
                context_lines=context_lines,
            )

    # ── incremental update hook (called after a change-set apply) ─────────────
    def apply_delta(self, *, modified=None, created=None, deleted=None, renamed=None) -> None:
        with self._lock:
            try:
                builder.apply_delta(
                    self._conn, self.repo,
                    modified=modified, created=created, deleted=deleted, renamed=renamed,
                )
            except Exception:
                logger.exception("codebase index apply_delta failed for %s", self.repo)


def get_index(repo: Path | str) -> CodebaseIndex:
    repo_path = Path(repo).resolve()
    key = _repo_hash(repo_path)
    with _HANDLES_LOCK:
        handle = _HANDLES.get(key)
        if handle is None:
            handle = CodebaseIndex(repo_path)
            _HANDLES[key] = handle
        return handle


__all__ = ["CodebaseIndex", "get_index"]
