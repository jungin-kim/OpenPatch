"""Read-side query API over the index.

Return shapes are kept byte-compatible with the previous
``find_file_candidates`` / ``search_text_matches`` so the SearchFilesTool and
SearchTextTool wrappers are unchanged.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from ..repo_files import candidate_priority, looks_like_glob
from ..secret_scanner import redact_secrets
from .config import MAX_TEXT_READ_BYTES
from .lexical import bm25_term_score, query_terms


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _redact_preview(text: str, *, limit: int = 240) -> str:
    redacted, _findings = redact_secrets(str(text or "")[:limit])
    return redacted


def _corpus_stats(conn: sqlite3.Connection) -> tuple[int, float]:
    row = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(token_count), 0) AS tot FROM files").fetchone()
    n_docs = int(row["n"] if row else 0)
    avg_len = (float(row["tot"]) / n_docs) if n_docs else 0.0
    return n_docs, avg_len


# ── search_files (backs find_file_candidates) ───────────────────────────────────

def search_files(
    conn: sqlite3.Connection,
    queries: list[str],
    *,
    text_queries: list[str] | None = None,
    max_results: int = 8,
) -> list[dict[str, Any]]:
    queries = _dedupe([str(q).strip() for q in queries if str(q).strip()])
    text_queries = [str(q).strip() for q in (text_queries or []) if str(q).strip()]

    rows = conn.execute("SELECT file_id, path FROM files").fetchall()
    path_by_id: dict[int, str] = {}
    scored: dict[str, dict[str, Any]] = {}

    def bump(path: str, delta: float, reason: str, matched_query: str) -> None:
        entry = scored.setdefault(path, {"path": path, "score": 0.0, "reasons": [], "matched": []})
        entry["score"] += delta
        entry["reasons"].append(reason)
        entry["matched"].append(matched_query)

    # Path / name / glob / extension signals (no file reads) — mirror the old weights.
    for row in rows:
        path_by_id[row["file_id"]] = row["path"]
        rel_text = row["path"]
        path_lower = rel_text.lower()
        p = Path(rel_text)
        name_lower = p.name.lower()
        stem_lower = p.stem.lower()
        for query in queries:
            lowered = query.lower()
            query_name = Path(query).name.lower()
            if lowered.startswith("*.") and p.suffix.lower() == lowered[1:]:
                bump(rel_text, 4.0, f"extension: {lowered}", query)
            elif looks_like_glob(query) and Path(rel_text).match(query):
                bump(rel_text, 42.0, f"glob: {query}", query)
            elif path_lower == lowered:
                bump(rel_text, 120.0, f"exact path: {query}", query)
            elif name_lower == query_name:
                bump(rel_text, 90.0, f"basename: {query_name}", query)
            elif query_name and query_name.rstrip(".cs") in stem_lower:
                bump(rel_text, 35.0, f"name contains: {query}", query)

    # Symbol signal for bare-word queries — precomputed symbols table (was regex-per-file).
    barewords = [q for q in queries if "." not in q and not q.startswith("*.")]
    if barewords:
        placeholders = ",".join("?" * len(barewords))
        for row in conn.execute(
            f"SELECT DISTINCT file_id, name FROM symbols WHERE name IN ({placeholders})",
            barewords,
        ):
            path = path_by_id.get(row["file_id"])
            if path:
                bump(path, 70.0, f"symbol: {row['name']}", row["name"])

    # Content signal for text_queries — BM25 over postings (was substring count).
    if text_queries:
        n_docs, avg_len = _corpus_stats(conn)
        for tq in text_queries:
            terms = query_terms(tq)
            if not terms:
                continue
            df_map: dict[str, int] = {}
            ph = ",".join("?" * len(terms))
            for row in conn.execute(f"SELECT term, df FROM terms WHERE term IN ({ph})", terms):
                df_map[row["term"]] = int(row["df"])
            file_scores: dict[int, float] = {}
            for term in terms:
                df = df_map.get(term, 0)
                if df <= 0:
                    continue
                for row in conn.execute(
                    "SELECT p.file_id AS fid, p.tf AS tf, f.token_count AS dl "
                    "FROM postings p JOIN files f ON f.file_id = p.file_id WHERE p.term = ?",
                    (term,),
                ):
                    file_scores[row["fid"]] = file_scores.get(row["fid"], 0.0) + bm25_term_score(
                        tf=int(row["tf"]), df=df, n_docs=n_docs, doc_len=int(row["dl"]), avg_len=avg_len
                    )
            for fid, raw in file_scores.items():
                path = path_by_id.get(fid)
                if path and raw > 0:
                    bump(path, min(60.0, raw * 14.0), f"contains: {tq}", tq)

    # Source-priority tie-break bonus (only on already-scored files).
    for entry in scored.values():
        rank = candidate_priority(Path(entry["path"]))
        entry["score"] += max(0.0, 5.0 - rank[0] - rank[1])

    results = [
        {
            "path": entry["path"],
            "score": round(entry["score"], 2),
            "reasons": _dedupe(entry["reasons"]),
            "matched_queries": _dedupe(entry["matched"]),
        }
        for entry in scored.values()
        if entry["score"] > 0
    ]
    results.sort(key=lambda item: (-float(item["score"]), item["path"]))
    return results[:max_results]


# ── lookup_symbol (new capability) ──────────────────────────────────────────────

def lookup_symbol(conn: sqlite3.Connection, name: str) -> list[dict[str, Any]]:
    name = str(name).strip()
    if not name:
        return []
    rows = conn.execute(
        "SELECT f.path AS path, s.name AS name, s.kind AS kind, s.line AS line, s.col AS col "
        "FROM symbols s JOIN files f ON f.file_id = s.file_id WHERE s.name = ? ORDER BY f.path, s.line",
        (name,),
    ).fetchall()
    return [
        {"path": r["path"], "name": r["name"], "kind": r["kind"], "line": r["line"], "col": r["col"]}
        for r in rows
    ]


# ── search_text (backs search_text_matches) ─────────────────────────────────────

def search_text(
    conn: sqlite3.Connection,
    repo: Path,
    *,
    query: str,
    path_globs: list[str],
    max_results: int,
    case_sensitive: bool,
    regex: bool,
    context_lines: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    # When no globs are given, search every catalogued file. (The previous
    # implementation defaulted to ["**/*"], which pathlib.match does not treat as
    # a recursive globstar, so top-level files were silently skipped.)
    patterns = [p for p in (path_globs or []) if p]
    matches: list[dict[str, Any]] = []
    files_searched = 0
    truncated = False
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled: re.Pattern[str] | None = None
    if regex:
        try:
            compiled = re.compile(query, flags=flags)
        except re.error as exc:
            return ([{"path": "", "line": 0, "column": 0, "preview": f"Invalid regex: {exc}"}], 0, False)
    needle = query if case_sensitive else query.lower()

    # Candidate files come from the catalog (no live tree walk), glob-filtered.
    candidate_paths = [
        row["path"]
        for row in conn.execute("SELECT path FROM files ORDER BY path")
        if not patterns or any(Path(row["path"]).match(pattern) for pattern in patterns)
    ]

    for rel_text in candidate_paths:
        if len(matches) >= max_results:
            truncated = True
            break
        abs_path = repo / rel_text
        try:
            raw = abs_path.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT_READ_BYTES]
        except OSError:
            continue
        files_searched += 1
        lines = raw.splitlines()
        for line_number, line in enumerate(lines, start=1):
            if len(matches) >= max_results:
                truncated = True
                break
            if compiled:
                found = next(compiled.finditer(line), None)
                if not found:
                    continue
                column = found.start() + 1
            else:
                haystack = line if case_sensitive else line.lower()
                idx = haystack.find(needle)
                if idx < 0:
                    continue
                column = idx + 1
            start_context = max(0, line_number - 1 - context_lines)
            end_context = min(len(lines), line_number + context_lines)
            before = [_redact_preview(item) for item in lines[start_context : line_number - 1]]
            after = [_redact_preview(item) for item in lines[line_number:end_context]]
            matches.append(
                {
                    "path": rel_text,
                    "line": line_number,
                    "column": column,
                    "preview": _redact_preview(line),
                    "before": before,
                    "after": after,
                }
            )
    return matches, files_searched, truncated
