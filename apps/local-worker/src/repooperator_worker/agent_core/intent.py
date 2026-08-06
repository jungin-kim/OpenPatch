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

# Identity questions aimed at the agent ("넌 누구야?"). The subject must be the
# agent (너/넌/너는/네가/당신) so questions about the repo's own actors
# ("이 봇은 누구한테 보내?") stay untouched.
_META_KO_IDENTITY_RE = re.compile(r"(?:^|\s)(?:너는|넌|너|네가|당신은|당신)\s*(?:는|이|가)?\s*누구")


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
    if _META_KO_IDENTITY_RE.search(text):
        return True
    return any(p in text for p in _META_KO)


_OFF_TOPIC_TERMS = (
    "날씨", "weather", "뉴스", "news", "주식", "stock price", "환율", "로또",
    "맛집", "레시피", "요리법", "노래 추천", "영화 추천", "농담", "tell me a joke",
    "몇 시야", "몇시야", "what time is it",
)
_REPO_TERMS = (
    "코드", "파일", "함수", "저장소", "레포", "repo", "code", "file", "function",
    "커밋", "commit", "브랜치", "branch", "버그", "bug", "테스트", "test",
    ".py", ".js", ".ts", ".md", "readme",
)


def is_off_topic_request(text: str) -> bool:
    """Obvious non-repository small talk (weather, news, jokes …).

    These used to grind through the full repo-analysis loop for many minutes.
    Only fires when an off-topic term appears AND nothing repo-related does.
    """
    if not text:
        return False
    lowered = text.lower()
    if not any(t in text or t in lowered for t in _OFF_TOPIC_TERMS):
        return False
    return not any(t in text or t in lowered for t in _REPO_TERMS)


def off_topic_answer(korean: bool) -> str:
    if korean:
        return (
            "죄송하지만 그건 제가 도와드릴 수 있는 범위 밖이에요. 저는 이 저장소의 코드를 읽고, 설명하고, "
            "수정 제안을 만들고, 테스트/커밋/PR을 도와드리는 코딩 에이전트입니다.\n\n"
            "저장소에 대해 궁금한 것이나 만들고 싶은 변경이 있으면 말씀해 주세요!"
        )
    return (
        "That's outside what I can help with — I'm a coding agent for this repository: I read and explain code, "
        "propose edits, and help with tests, commits, and PRs.\n\nAsk me anything about the repo or a change you'd like!"
    )


_PLANNING_TERMS = (
    "계획을 세워", "계획 세워", "계획해줘", "어떤 작업들이 필요", "무슨 작업이 필요",
    "단계별로", "단계로 나눠", "로드맵", "설계해줘", "어떻게 접근",
    "plan the", "make a plan", "step by step", "break it down", "roadmap", "what steps",
    "how would you approach",
)


def is_planning_request(text: str) -> bool:
    """Asking for a plan/breakdown — answer with the plan, don't ask what to do."""
    if not text:
        return False
    lowered = text.lower()
    return any(t in text or t in lowered for t in _PLANNING_TERMS)


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
