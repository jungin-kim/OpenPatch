from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repooperator_worker.agent_core.secret_scanner import redact_json_payload, redact_secrets, should_block_persistence
from repooperator_worker.services.common import get_repooperator_home_dir
from repooperator_worker.services.json_safe import json_safe


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    run_id: str
    kind: str
    path: str
    byte_size: int
    sha256: str
    preview: str
    created_at: str
    redacted: bool = False
    blocked: bool = False

    def record_dump(self) -> dict[str, Any]:
        return self.public_record_dump()

    def public_record_dump(self) -> dict[str, Any]:
        return json_safe(
            {
                "artifact_id": self.artifact_id,
                "run_id": self.run_id,
                "kind": self.kind,
                "byte_size": self.byte_size,
                "sha256": self.sha256,
                "preview": self.preview,
                "created_at": self.created_at,
                "redacted": self.redacted,
                "blocked": self.blocked,
            }
        )

    def internal_record_dump(self) -> dict[str, Any]:
        return json_safe(self)


class ArtifactStore:
    def __init__(self, *, base_dir: Path | None = None) -> None:
        if base_dir is not None:
            self.base_dir = base_dir
            return
        try:
            self.base_dir = get_repooperator_home_dir() / "artifacts"
        except PermissionError:
            self.base_dir = Path(tempfile.gettempdir()) / "repooperator-artifacts"

    def write(self, run_id: str, kind: str, payload: Any) -> ArtifactRecord:
        safe_run_id = _safe_segment(run_id or "run")
        safe_kind = _safe_segment(kind or "payload")
        artifact_id = f"art_{uuid.uuid4().hex[:12]}"
        redacted_payload, findings = redact_json_payload(payload)
        blocked = should_block_persistence(findings)
        payload_to_store: Any = (
            {"blocked": True, "reason": "high_confidence_secret_detected", "findings": [item.model_dump() for item in findings]}
            if blocked
            else redacted_payload
        )
        raw = json.dumps(json_safe(payload_to_store), ensure_ascii=False, indent=2).encode("utf-8")
        path = self._write_bytes(safe_run_id=safe_run_id, artifact_id=artifact_id, safe_kind=safe_kind, raw=raw)
        preview_text = json.dumps(json_safe(payload_to_store), ensure_ascii=False)[:600]
        preview_text, _preview_findings = redact_secrets(preview_text)
        return ArtifactRecord(
            artifact_id=artifact_id,
            run_id=run_id,
            kind=kind,
            path=str(path),
            byte_size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            preview=preview_text,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            redacted=bool(findings),
            blocked=blocked,
        )

    def read(self, artifact_id: str) -> Any:
        safe_id = _safe_segment(artifact_id)
        for path in self.base_dir.glob(f"*/{safe_id}-*.json"):
            return json.loads(path.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"Artifact not found: {artifact_id}")

    def _write_bytes(self, *, safe_run_id: str, artifact_id: str, safe_kind: str, raw: bytes) -> Path:
        target_dir = self.base_dir / safe_run_id
        path = target_dir / f"{artifact_id}-{safe_kind}.json"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            return path
        except PermissionError:
            self.base_dir = Path(tempfile.gettempdir()) / "repooperator-artifacts"
            target_dir = self.base_dir / safe_run_id
            path = target_dir / f"{artifact_id}-{safe_kind}.json"
            target_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            return path


_DEFAULT_ARTIFACT_STORE: ArtifactStore | None = None


def get_default_artifact_store() -> ArtifactStore:
    global _DEFAULT_ARTIFACT_STORE
    if _DEFAULT_ARTIFACT_STORE is None:
        _DEFAULT_ARTIFACT_STORE = ArtifactStore()
    return _DEFAULT_ARTIFACT_STORE


def _safe_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "artifact")).strip("._")
    return text[:80] or "artifact"
