"""SQLite persistence for the codebase index.

Holds the file catalog, the symbol table, and the inverted (BM25) postings. No
file *contents* are stored — only what is needed to rank; line-level results are
produced by re-reading the small candidate set on demand.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import SCHEMA_VERSION, SQLITE_BUSY_TIMEOUT_MS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS files (
    file_id      INTEGER PRIMARY KEY,
    path         TEXT UNIQUE NOT NULL,
    size         INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    content_sha1 TEXT NOT NULL,
    lang         TEXT NOT NULL,
    parse_mode   TEXT NOT NULL,
    token_count  INTEGER NOT NULL DEFAULT 0,
    indexed_at_ns INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS symbols (
    symbol_id INTEGER PRIMARY KEY,
    file_id   INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL,
    line      INTEGER NOT NULL,
    col       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);

CREATE TABLE IF NOT EXISTS postings (
    term    TEXT NOT NULL,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    tf      INTEGER NOT NULL,
    PRIMARY KEY (term, file_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_postings_file ON postings(file_id);

CREATE TABLE IF NOT EXISTS terms (
    term TEXT PRIMARY KEY,
    df   INTEGER NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (creating parent dirs + schema) a WAL-mode connection usable across threads."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ── meta helpers ────────────────────────────────────────────────────────────────

def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def schema_matches(conn: sqlite3.Connection) -> bool:
    return get_meta(conn, "schema_version") == str(SCHEMA_VERSION)


def stamp_schema(conn: sqlite3.Connection) -> None:
    set_meta(conn, "schema_version", str(SCHEMA_VERSION))


def file_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM files").fetchone()
    return int(row["n"] if row else 0)


def reset_all(conn: sqlite3.Connection) -> None:
    """Drop all indexed rows (used when schema is stale) but keep the schema."""
    conn.execute("DELETE FROM postings")
    conn.execute("DELETE FROM symbols")
    conn.execute("DELETE FROM terms")
    conn.execute("DELETE FROM files")
    conn.commit()
