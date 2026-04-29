import os
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderSettings:
    provider: str
    base_url: str | None
    token: str | None


WRITE_MODE_READ_ONLY = "read-only"
WRITE_MODE_WRITE_WITH_APPROVAL = "write-with-approval"
WRITE_MODE_AUTO_APPLY = "auto-apply"
_VALID_WRITE_MODES = {WRITE_MODE_READ_ONLY, WRITE_MODE_WRITE_WITH_APPROVAL}
AVAILABLE_WRITE_MODES = [
    WRITE_MODE_READ_ONLY,
    WRITE_MODE_WRITE_WITH_APPROVAL,
    WRITE_MODE_AUTO_APPLY,
]


@dataclass(frozen=True)
class Settings:
    repo_base_dir: Path
    default_command_timeout_seconds: int
    git_clone_timeout_seconds: int
    git_fetch_timeout_seconds: int
    git_push_timeout_seconds: int
    gitlab_base_url: str | None
    gitlab_token: str | None
    github_base_url: str | None
    github_token: str | None
    openai_base_url: str | None
    openai_api_key: str | None
    openai_model: str | None
    model_request_timeout_seconds: int
    repooperator_config_path: Path
    repooperator_home_dir: Path
    configured_git_provider: str | None
    configured_model_connection_mode: str | None
    configured_model_provider: str | None
    configured_model_name: str | None
    write_mode: str  # "read-only" | "write-with-approval"

    def get_provider_settings(self, provider: str) -> ProviderSettings:
        normalized = provider.strip().lower()
        if normalized == "gitlab":
            return ProviderSettings(
                provider="gitlab",
                base_url=self.gitlab_base_url,
                token=self.gitlab_token,
            )
        if normalized == "github":
            return ProviderSettings(
                provider="github",
                base_url=self.github_base_url,
                token=self.github_token,
            )
        raise ValueError(f"Unsupported git provider: {provider}")


def get_settings() -> Settings:
    repooperator_config_path = _get_repooperator_config_path()
    runtime_config = _load_runtime_config(repooperator_config_path)
    repo_base_dir = Path(
        os.getenv("LOCAL_REPO_BASE_DIR", Path.home() / ".repooperator" / "repos")
    ).expanduser().resolve()

    return Settings(
        repo_base_dir=repo_base_dir,
        default_command_timeout_seconds=int(
            os.getenv("REPOOPERATOR_COMMAND_TIMEOUT_SECONDS", "30")
        ),
        git_clone_timeout_seconds=int(os.getenv("REPOOPERATOR_GIT_CLONE_TIMEOUT_SECONDS", "300")),
        git_fetch_timeout_seconds=int(os.getenv("REPOOPERATOR_GIT_FETCH_TIMEOUT_SECONDS", "120")),
        git_push_timeout_seconds=int(os.getenv("REPOOPERATOR_GIT_PUSH_TIMEOUT_SECONDS", "180")),
        gitlab_base_url=_resolve_provider_value(
            env_value=os.getenv("GITLAB_BASE_URL"),
            runtime_config=runtime_config,
            provider="gitlab",
            key="baseUrl",
            normalizer=_normalize_optional_url,
        ),
        gitlab_token=_resolve_provider_value(
            env_value=os.getenv("GITLAB_TOKEN"),
            runtime_config=runtime_config,
            provider="gitlab",
            key="token",
            normalizer=_normalize_optional_value,
        ),
        github_base_url=_resolve_provider_value(
            env_value=os.getenv("GITHUB_BASE_URL"),
            runtime_config=runtime_config,
            provider="github",
            key="baseUrl",
            normalizer=_normalize_optional_url,
        ),
        github_token=_resolve_provider_value(
            env_value=os.getenv("GITHUB_TOKEN"),
            runtime_config=runtime_config,
            provider="github",
            key="token",
            normalizer=_normalize_optional_value,
        ),
        openai_base_url=_normalize_optional_url(os.getenv("OPENAI_BASE_URL")),
        openai_api_key=_normalize_optional_value(os.getenv("OPENAI_API_KEY")),
        openai_model=_normalize_optional_value(os.getenv("OPENAI_MODEL")),
        model_request_timeout_seconds=int(
            os.getenv("REPOOPERATOR_MODEL_REQUEST_TIMEOUT_SECONDS", "120")
        ),
        repooperator_config_path=repooperator_config_path,
        repooperator_home_dir=repooperator_config_path.parent,
        configured_git_provider=_resolve_configured_git_provider(runtime_config),
        configured_model_connection_mode=_resolve_configured_model_connection_mode(runtime_config),
        configured_model_provider=_resolve_configured_model_provider(runtime_config),
        configured_model_name=_resolve_configured_model_name(runtime_config),
        write_mode=_resolve_write_mode(runtime_config),
    )


def _get_repooperator_config_path() -> Path:
    configured = os.getenv("REPOOPERATOR_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    repooperator_path = (Path.home() / ".repooperator" / "config.json").resolve()
    return repooperator_path


def _load_runtime_config(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _resolve_provider_value(
    env_value: str | None,
    runtime_config: dict,
    provider: str,
    key: str,
    normalizer,
) -> str | None:
    env_normalized = normalizer(env_value)
    if env_normalized is not None:
        return env_normalized

    for provider_config in _iter_repository_source_configs(runtime_config):
        if provider_config.get("provider") == provider:
            return normalizer(provider_config.get(key))

    provider_config = runtime_config.get("gitProvider")
    if not isinstance(provider_config, dict):
        return None
    if provider_config.get("provider") != provider:
        return None
    return normalizer(provider_config.get(key))


def _iter_repository_source_configs(runtime_config: dict) -> list[dict]:
    sources = runtime_config.get("repositorySources")
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, dict)]


def _normalize_optional_url(value: str | None) -> str | None:
    normalized = _normalize_optional_value(value)
    if normalized is None:
        return None
    return normalized.rstrip("/")


def _normalize_optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_configured_git_provider(runtime_config: dict) -> str | None:
    provider_config = runtime_config.get("gitProvider")
    if not isinstance(provider_config, dict):
        return None
    provider = _normalize_optional_value(provider_config.get("provider"))
    if provider in {"gitlab", "github", "local"}:
        return provider
    return None


_LOCAL_RUNTIME_PROVIDERS = {"ollama", "vllm"}


def _resolve_configured_model_connection_mode(runtime_config: dict) -> str | None:
    model_config = runtime_config.get("model")
    if not isinstance(model_config, dict):
        return None
    connection_mode = _normalize_optional_value(model_config.get("connectionMode"))
    if connection_mode in {"local-runtime", "remote-api"}:
        return connection_mode
    provider = _normalize_optional_value(model_config.get("provider"))
    if provider in _LOCAL_RUNTIME_PROVIDERS:
        return "local-runtime"
    if provider:
        return "remote-api"
    return None


def _resolve_configured_model_provider(runtime_config: dict) -> str | None:
    model_config = runtime_config.get("model")
    if not isinstance(model_config, dict):
        return None
    return _normalize_optional_value(model_config.get("provider"))


def _resolve_configured_model_name(runtime_config: dict) -> str | None:
    model_config = runtime_config.get("model")
    if not isinstance(model_config, dict):
        return None
    return _normalize_optional_value(model_config.get("model"))


def _resolve_write_mode(runtime_config: dict) -> str:
    """Read the write mode from config, defaulting to read-only for safety.

    Config key: ``permissions.writeMode``
    Valid values: ``"read-only"`` (default), ``"write-with-approval"``

    This setting is intentionally conservative — it must be explicitly set in
    the config file to unlock write capabilities. Re-onboarding never resets
    this value because it is loaded fresh from the config file on every request.
    """
    env_value = os.getenv("REPOOPERATOR_WRITE_MODE")
    if env_value and env_value.strip().lower() in _VALID_WRITE_MODES:
        return env_value.strip().lower()

    permissions = runtime_config.get("permissions")
    if isinstance(permissions, dict):
        mode = _normalize_optional_value(permissions.get("writeMode"))
        if mode and mode.lower() in _VALID_WRITE_MODES:
            return mode.lower()

    return WRITE_MODE_READ_ONLY
