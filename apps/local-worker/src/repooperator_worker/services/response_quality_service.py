"""Small response cleanup helpers for user-visible agent text."""

from __future__ import annotations

import re

HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
THINK_RE = re.compile(r"<think>(.*?)</think>", re.IGNORECASE | re.DOTALL)
CODE_OR_PATH_RE = re.compile(r"(`[^`]*`|[\w./-]+\.[A-Za-z0-9]{1,8})")
STANDALONE_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
GARBLED_KOREAN_RE = re.compile(r"[\uac00-\ud7a3][A-Za-z]{3,}|[A-Za-z]{3,}[\uac00-\ud7a3]|[\uac00-\ud7a3][\u4e00-\u9fff]+")
# Latin words written next to Hangul are normal Korean prose ("RepoOperator\uc785\ub2c8\ub2e4",
# "Python\uc73c\ub85c"), not garbled mixed script. Protect them before the garbled-text
# repair runs, or it strips the word and leaves "\uc800\ub294 \uc785\ub2c8\ub2e4".
LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.-]*")


_ENGLISH_OPENER_RE = re.compile(
    r"^\s*(what|how|why|when|where|who|which|does|do|is|are|can|could|would|should|please|explain|describe|show|list|tell)\b",
    re.IGNORECASE,
)


def user_prefers_korean(text: str) -> bool:
    """Korean if the task contains Hangul — unless the sentence itself is an
    English question/imperative ("What does the /관리자 로그 command do?"),
    where the only Hangul is an identifier being asked about."""
    text = text or ""
    if not HANGUL_RE.search(text):
        return False
    return not _ENGLISH_OPENER_RE.match(text)


def split_visible_reasoning(text: str) -> tuple[str, str | None]:
    """Separate model-provided <think> blocks from the visible final answer."""
    reasoning_parts = [match.group(1).strip() for match in THINK_RE.finditer(text or "")]
    visible = THINK_RE.sub("", text or "").strip()
    reasoning = "\n\n".join(part for part in reasoning_parts if part) or None
    return visible, reasoning


def clean_user_visible_response(text: str, *, user_task: str = "") -> tuple[str, str | None]:
    """Remove visible thinking tags and repair a few common malformed artifacts.

    This is deliberately conservative. It does not invent content or alter code
    identifiers; it only strips model-visible thinking tags and cleans obvious
    mixed-script artifacts seen in manual testing.
    """
    visible, reasoning = split_visible_reasoning(text)
    cleaned = visible
    if user_prefers_korean(user_task):
        cleaned = _repair_korean_visible_text(cleaned, user_task=user_task)
    return cleaned.strip(), reasoning


def _repair_korean_visible_text(text: str, *, user_task: str) -> str:
    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"@@RO_PROTECTED_{len(protected) - 1}@@"

    cleaned = CODE_OR_PATH_RE.sub(protect, text)
    # Protect Latin words (product/library/identifier names) so the garbled-text
    # repair below only touches genuinely mixed-script artifacts. This pass also
    # re-protects the placeholders themselves (they are Latin), so restoration
    # below must run in reverse to unwrap the nesting.
    cleaned = LATIN_WORD_RE.sub(protect, cleaned)
    replacements = {
        "외부依赖": "외부 의존성",
        "내부依赖": "내부 의존성",
        "결과디오는": "결과 비디오는",
        "자바스크립트 스크립트": "Python 스크립트" if ".py" in user_task else "스크립트",
    }
    for bad, good in replacements.items():
        cleaned = cleaned.replace(bad, good)
    # Remove short, obvious malformed mixed-script fragments in prose only.
    cleaned = GARBLED_KOREAN_RE.sub(lambda match: _safe_korean_fragment(match.group(0)), cleaned)
    # Standalone Chinese phrases also leak into Korean answers ("让您 질문하신
    # ... 这个问题") — the adjacency pattern above misses them because they are
    # separated by punctuation/whitespace. Korean prose has no legitimate runs
    # of CJK ideographs here (code spans are already protected).
    cleaned = STANDALONE_CJK_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    for index in range(len(protected) - 1, -1, -1):
        cleaned = cleaned.replace(f"@@RO_PROTECTED_{index}@@", protected[index])
    return cleaned


def _safe_korean_fragment(fragment: str) -> str:
    if len(fragment) > 24:
        return fragment
    hangul = "".join(ch for ch in fragment if HANGUL_RE.match(ch))
    return hangul or fragment


def language_guidance_for_task(task: str) -> str:
    if user_prefers_korean(task):
        return (
            "The user asked in Korean. Answer in natural Korean. Keep code identifiers, "
            "file paths, and commands in their original spelling. Do not mix Chinese, "
            "Japanese, or garbled multilingual tokens. If the file is Python, describe "
            "it as Python, not JavaScript."
        )
    return (
        "The user asked in English — answer entirely in English, even when the question "
        "mentions identifiers or command names written in another script (keep those "
        "identifiers in their original spelling, but all prose must be English). "
        "Never mix Chinese, Korean, or garbled multilingual tokens into the prose."
    )
