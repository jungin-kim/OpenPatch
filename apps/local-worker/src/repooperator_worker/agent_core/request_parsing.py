from __future__ import annotations

import re


FILE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_./\\-])([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]{1,8})(?![A-Za-z0-9_./\\-])")


def extract_file_tokens(text: str) -> list[str]:
    files: list[str] = []
    for match in FILE_TOKEN_RE.finditer(text or ""):
        candidate = match.group(1).strip("`'\".,)")
        if candidate.lower().startswith(("http://", "https://")):
            continue
        if candidate not in files:
            files.append(candidate)
    return files


def file_tokens(text: str) -> list[str]:
    return extract_file_tokens(text)
