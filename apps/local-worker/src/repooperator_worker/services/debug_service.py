from repooperator_worker.config import get_settings
from repooperator_worker.services.active_repository import get_active_repository
from repooperator_worker.services.composio_service import get_composio_status
from repooperator_worker.services.event_service import list_recent_runs
from repooperator_worker.services.memory_service import list_memory_items
from repooperator_worker.services.permissions_service import permission_profile
from repooperator_worker.services.skills_service import discover_skills


def get_debug_runtime_status() -> dict:
    settings = get_settings()
    active = get_active_repository()
    profile = permission_profile(settings.permission_mode)
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
            "mode": profile["mode"],
            "sandbox": profile["sandbox"],
            "approval": profile["approval"],
            "tools": profile["tools"],
        },
        "repository": {
            "source": active.git_provider if active else None,
            "project_path": active.project_path if active else None,
            "branch": active.branch if active else None,
        },
        "agent": {
            "orchestration_mode": "LangGraph",
        },
        "recent_runs": list_recent_runs(),
    }


def integration_status() -> dict:
    try:
        status = get_composio_status()
    except RuntimeError as exc:
        status = {
            "provider": "Composio",
            "status": "error",
            "configured": True,
            "message": str(exc),
            "accounts": [],
            "toolkits": [],
            "tools_count": 0,
        }
    return {"integrations": [status]}
