import json
from pathlib import Path

from repooperator_worker.config import (
    AVAILABLE_WRITE_MODES,
    WRITE_MODE_AUTO_APPLY,
    WRITE_MODE_READ_ONLY,
    WRITE_MODE_WRITE_WITH_APPROVAL,
    get_settings,
)
from repooperator_worker.schemas import PermissionModeResponse

SUPPORTED_WRITE_MODES = {WRITE_MODE_READ_ONLY, WRITE_MODE_WRITE_WITH_APPROVAL, WRITE_MODE_AUTO_APPLY}


def get_permission_mode() -> PermissionModeResponse:
    settings = get_settings()
    return PermissionModeResponse(
        write_mode=settings.write_mode,
        available_modes=AVAILABLE_WRITE_MODES,
        unsupported_modes=[],
    )


def update_permission_mode(write_mode: str) -> PermissionModeResponse:
    mode = write_mode.strip().lower()
    if mode not in AVAILABLE_WRITE_MODES:
        raise ValueError("Unsupported permission mode.")
    settings = get_settings()
    config = _read_config(settings.repooperator_config_path)
    permissions = config.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    permissions["writeMode"] = mode
    config["permissions"] = permissions
    _write_config(settings.repooperator_config_path, config)

    return PermissionModeResponse(
        write_mode=mode,
        available_modes=AVAILABLE_WRITE_MODES,
        unsupported_modes=[],
    )


def _read_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_config(config_path: Path, config: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_name(f"{config_path.name}.tmp")
    tmp_path.write_text(json.dumps(config, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    tmp_path.replace(config_path)
