from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from repooperator_worker.services.json_safe import json_safe


@dataclass(frozen=True)
class SecretFinding:
    kind: str
    start: int
    end: int
    confidence: str
    preview: str

    def model_dump(self) -> dict[str, Any]:
        return json_safe(self)


SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack_token", re.compile(r"\bx(?:ox[baprs]|app)-[A-Za-z0-9-]{10,}\b")),
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL)),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
]


def scan_text_for_secrets(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text or ""):
            value = match.group(0)
            findings.append(
                SecretFinding(
                    kind=kind,
                    start=match.start(),
                    end=match.end(),
                    confidence="high",
                    preview=_preview(value),
                )
            )
    return _dedupe_findings(findings)


def redact_secrets(text: str) -> tuple[str, list[SecretFinding]]:
    findings = scan_text_for_secrets(text)
    if not findings:
        return text, []
    redacted = text
    for finding in sorted(findings, key=lambda item: item.start, reverse=True):
        redacted = redacted[: finding.start] + f"[REDACTED:{finding.kind}]" + redacted[finding.end :]
    return redacted, findings


def scan_json_payload(payload: Any) -> list[SecretFinding]:
    try:
        text = json.dumps(json_safe(payload), ensure_ascii=False)
    except Exception:
        text = str(payload)
    return scan_text_for_secrets(text)


def redact_json_payload(payload: Any) -> tuple[Any, list[SecretFinding]]:
    safe = json_safe(payload)
    if isinstance(safe, str):
        return redact_secrets(safe)
    text = json.dumps(safe, ensure_ascii=False)
    redacted_text, findings = redact_secrets(text)
    if not findings:
        return safe, []
    try:
        return json.loads(redacted_text), findings
    except json.JSONDecodeError:
        return {"redacted_payload": redacted_text}, findings


def should_block_persistence(findings: list[SecretFinding]) -> bool:
    return any(item.kind == "private_key" for item in findings)


def _preview(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return value[:4] + "..." + value[-4:]


def _dedupe_findings(findings: list[SecretFinding]) -> list[SecretFinding]:
    seen: set[tuple[int, int, str]] = set()
    result: list[SecretFinding] = []
    for finding in sorted(findings, key=lambda item: (item.start, item.end, item.kind)):
        key = (finding.start, finding.end, finding.kind)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return result
