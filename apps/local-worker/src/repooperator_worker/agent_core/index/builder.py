"""Build and incrementally update the codebase index."""
from __future__ import annotations

import sqlite3
import time
from collections import Counter
from pathlib import Path

from ..repo_files import is_supported_text_file
from . import catalog, store, symbols as symbols_mod
from .config import BUILD_TIME_BUDGET_S, MAX_FILE_BYTES, MAX_TEXT_READ_BYTES
from .lexical import tokenize


def _read_text_capped(abs_path: Path) -> str:
    try:
        with abs_path.open("rb") as fh:
            raw = fh.read(MAX_TEXT_READ_BYTES)
    except OSError:
        return ""
    return raw.decode("utf-8", "replace")


def _decrement_terms(conn: sqlite3.Connection, terms: list[str]) -> None:
    for term in terms:
        conn.execute("UPDATE terms SET df = df - 1 WHERE term = ?", (term,))
    conn.execute("DELETE FROM terms WHERE df <= 0")


def _increment_terms(conn: sqlite3.Connection, terms) -> None:
    for term in terms:
        conn.execute(
            "INSERT INTO terms(term, df) VALUES(?, 1) "
            "ON CONFLICT(term) DO UPDATE SET df = df + 1",
            (term,),
        )


def remove_file(conn: sqlite3.Connection, rel_posix: str) -> None:
    row = conn.execute("SELECT file_id FROM files WHERE path = ?", (rel_posix,)).fetchone()
    if row is None:
        return
    file_id = row["file_id"]
    old_terms = [r["term"] for r in conn.execute("SELECT term FROM postings WHERE file_id = ?", (file_id,))]
    _decrement_terms(conn, old_terms)
    conn.execute("DELETE FROM files WHERE file_id = ?", (file_id,))  # cascades postings/symbols


def index_file(conn: sqlite3.Connection, rel_posix: str, abs_path: Path) -> bool:
    """(Re)index a single file. Returns True if indexed, False if skipped/removed."""
    if not is_supported_text_file(abs_path):
        remove_file(conn, rel_posix)
        return False
    try:
        st = abs_path.stat()
    except OSError:
        remove_file(conn, rel_posix)
        return False

    sha = catalog.content_sha1(abs_path)
    lang = catalog.lang_for(abs_path)
    text = _read_text_capped(abs_path)
    tf: Counter = tokenize(text) if st.st_size <= MAX_FILE_BYTES else Counter()
    syms, parse_mode = symbols_mod.extract_symbols(text, lang)
    token_count = int(sum(tf.values()))
    now_ns = time.time_ns()

    row = conn.execute("SELECT file_id FROM files WHERE path = ?", (rel_posix,)).fetchone()
    if row is not None:
        file_id = row["file_id"]
        old_terms = [r["term"] for r in conn.execute("SELECT term FROM postings WHERE file_id = ?", (file_id,))]
        _decrement_terms(conn, old_terms)
        conn.execute("DELETE FROM postings WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        conn.execute(
            "UPDATE files SET size=?, mtime_ns=?, content_sha1=?, lang=?, parse_mode=?, "
            "token_count=?, indexed_at_ns=? WHERE file_id=?",
            (int(st.st_size), int(st.st_mtime_ns), sha, lang, parse_mode, token_count, now_ns, file_id),
        )
    else:
        cur = conn.execute(
            "INSERT INTO files(path, size, mtime_ns, content_sha1, lang, parse_mode, token_count, indexed_at_ns) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (rel_posix, int(st.st_size), int(st.st_mtime_ns), sha, lang, parse_mode, token_count, now_ns),
        )
        file_id = cur.lastrowid

    if tf:
        conn.executemany(
            "INSERT INTO postings(term, file_id, tf) VALUES(?, ?, ?)",
            [(term, file_id, count) for term, count in tf.items()],
        )
        _increment_terms(conn, tf.keys())
    if syms:
        conn.executemany(
            "INSERT INTO symbols(file_id, name, kind, line, col) VALUES(?, ?, ?, ?, ?)",
            [(file_id, s.name, s.kind, s.line, s.col) for s in syms],
        )
    return True


def build(conn: sqlite3.Connection, repo: Path, *, budget_s: float = BUILD_TIME_BUDGET_S) -> dict:
    """Full (re)build. Resets rows, then indexes within a soft time budget.

    A partial build (budget exceeded) is persisted and marked ``partial=1``;
    the next refresh_stale picks up the not-yet-indexed files as 'new'.
    """
    store.reset_all(conn)
    store.stamp_schema(conn)
    store.set_meta(conn, "repo_path", str(repo.resolve()))
    store.set_meta(conn, "build_in_progress", "1")
    store.set_meta(conn, "tree_sitter_available", "1" if symbols_mod.tree_sitter_available() else "0")
    conn.commit()

    records, truncated = catalog.scan(repo)
    start = time.monotonic()
    indexed = 0
    partial = False
    for record in records:
        index_file(conn, record.rel_path, record.abs_path)
        indexed += 1
        if indexed % 200 == 0:
            conn.commit()
            if time.monotonic() - start > budget_s:
                partial = True
                break

    store.set_meta(conn, "truncated", "1" if truncated else "0")
    store.set_meta(conn, "partial", "1" if partial else "0")
    store.set_meta(conn, "build_in_progress", "0")
    store.set_meta(conn, "built_at_ns", str(time.time_ns()))
    conn.commit()
    return {"indexed": indexed, "truncated": truncated, "partial": partial}


def refresh_stale(conn: sqlite3.Connection, repo: Path) -> dict:
    """Reconcile the index with the working tree using cheap (size, mtime) diffing."""
    sig = catalog.stat_signature(repo)  # {rel: (size, mtime_ns)}
    existing = {
        row["path"]: (int(row["size"]), int(row["mtime_ns"]), row["content_sha1"])
        for row in conn.execute("SELECT path, size, mtime_ns, content_sha1 FROM files")
    }

    added = changed = removed = 0

    # Deletions: indexed paths no longer present.
    for path in list(existing.keys()):
        if path not in sig:
            remove_file(conn, path)
            removed += 1

    # Additions / modifications.
    for path, (size, mtime_ns) in sig.items():
        prior = existing.get(path)
        abs_path = repo / path
        if prior is None:
            if index_file(conn, path, abs_path):
                added += 1
            continue
        prior_size, prior_mtime, prior_sha = prior
        if size == prior_size and mtime_ns == prior_mtime:
            continue  # unchanged
        # Metadata differs — confirm real content change before reparsing.
        new_sha = catalog.content_sha1(abs_path)
        if new_sha and new_sha == prior_sha:
            conn.execute("UPDATE files SET mtime_ns = ? WHERE path = ?", (mtime_ns, path))
            continue
        if index_file(conn, path, abs_path):
            changed += 1

    if added or changed or removed:
        conn.commit()
    return {"added": added, "changed": changed, "removed": removed}


def apply_delta(conn: sqlite3.Connection, repo: Path, *, modified=None, created=None, deleted=None, renamed=None) -> None:
    """Immediate incremental update after a change-set apply. Best-effort."""
    for rel in list(created or []) + list(modified or []):
        index_file(conn, Path(rel).as_posix(), repo / rel)
    for rel in deleted or []:
        remove_file(conn, Path(rel).as_posix())
    for item in renamed or []:
        src = item.get("from")
        dst = item.get("to")
        if src:
            remove_file(conn, Path(src).as_posix())
        if dst:
            index_file(conn, Path(dst).as_posix(), repo / dst)
    conn.commit()
