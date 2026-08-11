"""Tunable limits and constants for the codebase index."""
from __future__ import annotations

# Bump when the on-disk schema or indexing semantics change; a mismatch forces a
# full rebuild.
SCHEMA_VERSION = 1

# ── Build cost bounds ───────────────────────────────────────────────────────────
MAX_INDEX_FILES = 20_000          # stop cataloguing beyond this many files
MAX_FILE_BYTES = 1_000_000        # files larger than this are cataloged but not tokenized
MAX_TOKENS_PER_FILE = 50_000      # cap tokens fed to the lexical index per file
MAX_TEXT_READ_BYTES = 240_000     # cap bytes read for tokenizing/line-scanning (matches builtin)
BUILD_TIME_BUDGET_S = 30.0        # soft budget for a full build; overflow persists partial

# ── BM25 parameters ─────────────────────────────────────────────────────────────
BM25_K1 = 1.5
BM25_B = 0.75

# SQLite busy timeout (ms) for cross-thread contention on the single connection.
SQLITE_BUSY_TIMEOUT_MS = 5_000
