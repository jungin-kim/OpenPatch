"""File enumeration, hashing, and language detection for the index."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from ..repo_files import (
    SKIP_DIRS,
    is_stale_duplicate_copy,
    is_supported_text_file,
)
from .config import MAX_INDEX_FILES

# Map file suffix → tree-sitter language name (also used as the stored ``lang``).
SUFFIX_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".kt": "kotlin",
    ".swift": "swift",
}


def lang_for(path: Path) -> str:
    return SUFFIX_TO_LANG.get(path.suffix.lower(), "text")


@dataclass
class FileRecord:
    rel_path: str          # repo-relative, posix separators
    abs_path: Path
    size: int
    mtime_ns: int
    lang: str


def _iter_files(repo: Path):
    """Yield (abs_path, rel_posix) for candidate files, pruning SKIP_DIRS at dir level.

    Uses os.scandir (never rglob) so vendored trees like node_modules are pruned
    before descent instead of after.
    """
    repo = repo.resolve()
    stack: list[Path] = [repo]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if name in SKIP_DIRS:
                        continue
                    stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            abs_path = Path(entry.path)
            try:
                rel = abs_path.relative_to(repo)
            except ValueError:
                continue
            if is_stale_duplicate_copy(rel):
                continue
            yield abs_path, rel.as_posix()


def scan(repo: Path) -> tuple[list[FileRecord], bool]:
    """Return (records, truncated) for all indexable files under ``repo``.

    Metadata-only (stat, plus the small binary sniff in is_supported_text_file).
    """
    records: list[FileRecord] = []
    truncated = False
    for abs_path, rel_posix in _iter_files(repo):
        if len(records) >= MAX_INDEX_FILES:
            truncated = True
            break
        if not is_supported_text_file(abs_path):
            continue
        try:
            st = abs_path.stat()
        except OSError:
            continue
        records.append(
            FileRecord(
                rel_path=rel_posix,
                abs_path=abs_path,
                size=int(st.st_size),
                mtime_ns=int(st.st_mtime_ns),
                lang=lang_for(abs_path),
            )
        )
    return records, truncated


def stat_signature(repo: Path) -> dict[str, tuple[int, int]]:
    """Cheap {rel_path: (size, mtime_ns)} map for staleness diffing (no reads)."""
    sig: dict[str, tuple[int, int]] = {}
    count = 0
    for abs_path, rel_posix in _iter_files(repo):
        if count >= MAX_INDEX_FILES:
            break
        try:
            st = abs_path.stat()
        except OSError:
            continue
        # Cheap suffix/basename gate mirrors is_supported_text_file without the
        # 4KB binary sniff (kept out of the hot staleness path).
        sig[rel_posix] = (int(st.st_size), int(st.st_mtime_ns))
        count += 1
    return sig


def content_sha1(abs_path: Path) -> str:
    h = hashlib.sha1()
    try:
        with abs_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()
