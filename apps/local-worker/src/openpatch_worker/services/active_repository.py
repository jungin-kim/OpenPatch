import json
from dataclasses import asdict, dataclass
from pathlib import Path

from openpatch_worker.services.common import get_repooperator_home_dir


@dataclass(frozen=True)
class ActiveRepository:
    git_provider: str
    project_path: str
    local_repo_path: str
    branch: str | None
    head_sha: str | None


def set_active_repository(context: ActiveRepository) -> None:
    path = _active_repository_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(context), indent=2), encoding="utf-8")


def get_active_repository() -> ActiveRepository | None:
    path = _active_repository_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    try:
        return ActiveRepository(
            git_provider=str(payload["git_provider"]),
            project_path=str(payload["project_path"]),
            local_repo_path=str(payload["local_repo_path"]),
            branch=payload.get("branch"),
            head_sha=payload.get("head_sha"),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _active_repository_path() -> Path:
    return get_repooperator_home_dir() / "run" / "active-repository.json"
