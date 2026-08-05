"""Deterministic intent signals extracted from the raw user task.

RepoOperator historically forced every request into "analyze the open repo",
which made it ignore URLs and answer meta/capability questions with a repo
summary. These helpers give the router strong, cheap signals so web-fetch,
meta/capability, and @file-reference intents are handled for what they are.
"""

from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s<>\"'`)\]}]+", re.IGNORECASE)
# @path references (e.g. @src/main.py, @README.md) — deterministic file targets.
_AT_REF_RE = re.compile(r"(?:^|\s)@([A-Za-z0-9._/\-]+\.[A-Za-z0-9]+)")

_META_EN = (
    "what can you do",
    "what can you help",
    "what do you do",
    "what are you capable",
    "what are your capabilities",
    "who are you",
    "how do i use you",
    "how can i use you",
    "how do you work",
    "what can this agent",
)
_META_KO = (
    "뭘 해줄",
    "뭘해줄",
    "무엇을 해줄",
    "뭘 할 수",
    "뭘할 수",
    "무엇을 할 수",
    "뭐 할 수 있",
    "뭐할 수 있",
    "너 뭐",
    "넌 뭐",
    "사용법",
    "어떻게 사용",
    "어떻게 쓰",
    "도움말",
    "무슨 기능",
    "어떤 기능",
)


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in _URL_RE.findall(text or ""):
        cleaned = match.rstrip(".,;")
        if cleaned not in urls:
            urls.append(cleaned)
    return urls


def extract_at_file_refs(text: str) -> list[str]:
    refs: list[str] = []
    for match in _AT_REF_RE.findall(text or ""):
        candidate = match.strip("`'\".,)")
        if candidate and candidate not in refs:
            refs.append(candidate)
    return refs


def is_meta_request(text: str) -> bool:
    """Whether the user is asking about the agent itself (capabilities/help),
    not about the repository."""
    if not text:
        return False
    lowered = text.lower()
    if any(p in lowered for p in _META_EN):
        return True
    return any(p in text for p in _META_KO)


def has_web_intent(text: str) -> bool:
    if extract_urls(text):
        return True
    lowered = (text or "").lower()
    web_phrases = ("이 페이지", "이 사이트", "이 링크", "웹페이지", "웹 페이지", "read this page", "read the page", "this url", "this link", "fetch this")
    return any(p in text or p in lowered for p in web_phrases)


def capability_answer(repo_name: str | None = None) -> str:
    """A grounded answer to "what can you do?" built from the real tool set and
    skills, instead of forcing a repository summary."""
    tool_count = 33
    skills: list[str] = []
    try:
        from repooperator_worker.agent_core.tools.registry import get_default_tool_registry

        tool_count = len(get_default_tool_registry().specs_for_model(include_deferred=True))
    except Exception:
        pass
    try:
        from repooperator_worker.services.skills_service import discover_skills

        skills = [str(s.get("name") or s.get("slug") or "") for s in (discover_skills() or []) if isinstance(s, dict)]
        skills = [s for s in skills if s][:8]
    except Exception:
        skills = []

    where = f" **{repo_name}**" if repo_name else " the opened repository"
    lines = [
        f"I'm RepoOperator — a local-first coding agent working directly on{where}. I can:",
        "",
        "- **Understand code** — read files, search, and map the repo structure to answer questions with real evidence.",
        "- **Make changes** — propose file edits (create / modify / delete / rename) as a reviewable diff you Apply, on your machine.",
        "- **Run & verify** — run approved commands and validation/tests (with an approval gate).",
        "- **Git & PRs** — create branches, commit, push, and open GitHub PRs / GitLab MRs.",
        "- **Web research** — fetch a URL or search the web when you ask (approval-gated).",
        "- **Extend** — MCP plugins and sub-agents for larger tasks.",
        "",
        f"That's {tool_count} built-in tools" + (f" plus skills like {', '.join(skills)}." if skills else "."),
        "",
        "Try: \"add a docstring to greet() in main.py\", \"summarize this repo\", \"commit these changes\", or \"fetch https://… and summarize it\".",
    ]
    return "\n".join(lines)
