from pathlib import Path

from repooperator_worker.config import get_settings
from repooperator_worker.services.active_repository import get_active_repository


def get_debug_runtime_status() -> dict:
    settings = get_settings()
    active = get_active_repository()
    return {
        "worker": {
            "status": "ok",
            "service": "repooperator-local-worker",
        },
        "model": {
            "provider": settings.configured_model_provider,
            "connection_mode": settings.configured_model_connection_mode,
            "name": settings.configured_model_name,
            "base_url": settings.openai_base_url,
        },
        "permissions": {
            "write_mode": settings.write_mode,
        },
        "repository": {
            "source": active.git_provider if active else None,
            "project_path": active.project_path if active else None,
            "branch": active.branch if active else None,
        },
        "agent": {
            "orchestration_mode": "LangGraph",
        },
        "recent_runs": [],
    }


def list_memory_items() -> dict:
    return {
        "items": [],
        "graph": {"nodes": [], "edges": []},
    }


def discover_skills() -> dict:
    settings = get_settings()
    active = get_active_repository()
    roots: list[Path] = []
    if active:
        try:
            from repooperator_worker.services.common import resolve_project_path

            roots.append(resolve_project_path(active.project_path))
        except Exception:
            pass
    roots.append(settings.repooperator_home_dir / "skills")

    skills: list[dict] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("skills.md"):
            skills.extend(_parse_skills_file(path))
        direct = root / "skills.md"
        if direct.exists():
            skills.extend(_parse_skills_file(direct))

    deduped: dict[str, dict] = {}
    for skill in skills:
        deduped[f"{skill['source_path']}::{skill['name']}"] = skill
    return {"skills": list(deduped.values())}


def integration_status() -> dict:
    settings = get_settings()
    composio_configured = bool(
        getattr(settings, "composio_api_key", None)
    )
    return {
        "integrations": [
            {
                "provider": "Composio",
                "status": "connected" if composio_configured else "not configured",
                "account": None,
                "tools_count": 0,
                "message": "Composio connection flow is coming soon.",
            }
        ]
    }


def _parse_skills_file(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    skills: list[dict] = []
    current_name: str | None = None
    current_desc: list[str] = []
    for line in lines:
        if line.startswith("#"):
            if current_name:
                skills.append(
                    {
                        "name": current_name,
                        "source_path": str(path),
                        "description": " ".join(current_desc).strip(),
                        "enabled": False,
                    }
                )
            current_name = line.lstrip("#").strip() or path.stem
            current_desc = []
        elif current_name and line.strip():
            current_desc.append(line.strip())
    if current_name:
        skills.append(
            {
                "name": current_name,
                "source_path": str(path),
                "description": " ".join(current_desc).strip(),
                "enabled": False,
            }
        )
    return skills
