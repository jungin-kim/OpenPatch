"""Low-level, dependency-light repository file primitives.

This module is the single home for the constants and helpers that decide which
files are worth indexing/searching. It deliberately imports nothing heavy so the
codebase index (agent_core/index/*) and the builtin search tools can both share
it without an import cycle.

Historically ``SKIP_DIRS`` was duplicated in three places
(``agent_core/tools/builtin.py`` twice and ``services/retrieval_service.py``);
this is now the canonical definition and those modules re-import from here.
"""
from __future__ import annotations

import re
from pathlib import Path

# ── Directories never worth walking into ────────────────────────────────────────
# Union of the previously duplicated sets. Skipping extra build/cache dirs never
# hurts source discovery — it only avoids junk and huge vendored trees.
SKIP_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", ".claude",
    "node_modules", "runtime",
    ".next", "dist", "build", "out", "target",
    ".cache", ".pytest_cache", "htmlcov", ".mypy_cache", ".ruff_cache", ".tox",
    "coverage",
    ".venv", "venv", "env", ".env",
    "__pycache__",
})

# ── Text-file classification (mirrors the long-standing builtin gate) ───────────
TEXT_FILE_SUFFIXES: frozenset[str] = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx", ".cs", ".java", ".kt", ".go", ".rs", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp", ".md", ".txt", ".rst", ".json", ".toml", ".yaml", ".yml",
    ".ini", ".cfg", ".gradle", ".xml", ".html", ".css", ".sh",
})
TEXT_FILE_BASENAMES: frozenset[str] = frozenset({"readme", "makefile", "dockerfile", "license"})
BINARY_OR_CACHE_SUFFIXES: frozenset[str] = frozenset({
    ".sqlite", ".sqlite3", ".db", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip",
    ".tar", ".gz", ".7z", ".dll", ".exe", ".so", ".dylib", ".class", ".jar", ".bin",
})

# Source-code suffixes used for priority ranking (a subset of TEXT_FILE_SUFFIXES).
_SOURCE_SUFFIXES: frozenset[str] = frozenset({
    ".cs", ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt",
    ".swift", ".rb", ".php", ".c", ".cpp", ".h", ".hpp",
})


def is_skipped_path(relative_path: Path) -> bool:
    """True when any path component is a skip directory."""
    return any(part in SKIP_DIRS for part in relative_path.parts)


def is_stale_duplicate_copy(relative_path: Path) -> bool:
    """Detect editor/OS duplicate artefacts like ``foo 2.py``, ``foo copy.py``, ``x.bak``."""
    return bool(
        re.search(r"(?:\s+\d+|\s+copy)(?=\.[^.]+$)|\.(?:bak|orig)$", str(relative_path), flags=re.IGNORECASE)
    )


def is_supported_text_file(path: Path) -> bool:
    """True when the file is a small-enough, non-binary text/source file."""
    suffix = path.suffix.lower()
    if suffix in BINARY_OR_CACHE_SUFFIXES:
        return False
    if suffix not in TEXT_FILE_SUFFIXES and path.name.lower() not in TEXT_FILE_BASENAMES:
        return False
    try:
        sample = path.read_bytes()[:4096]
    except OSError:
        return False
    if b"\x00" in sample:
        return False
    if not sample:
        return True
    controlish = sum(1 for byte in sample if byte < 9 or (13 < byte < 32))
    return (controlish / max(1, len(sample))) < 0.05


def candidate_priority(relative_path: Path) -> tuple[int, int, str]:
    """Rank tuple: source files under src/app dirs first, then shallower, then name."""
    parts = [part.lower() for part in relative_path.parts]
    source = 0 if relative_path.suffix.lower() in _SOURCE_SUFFIXES else 1
    source_dir = 0 if any(part in {"assets", "scripts", "src", "app", "apps"} for part in parts) else 1
    return (source + source_dir, len(relative_path.parts), str(relative_path).lower())


def looks_like_glob(value: str) -> bool:
    return "*" in value or "?" in value or "[" in value
