import base64
import logging
from dataclasses import dataclass

from openpatch_worker.config import ProviderSettings, Settings

logger = logging.getLogger(__name__)


SUPPORTED_GIT_PROVIDERS = {"gitlab", "github"}


@dataclass(frozen=True)
class ProviderGitOptions:
    provider: str
    clone_url: str
    git_config_args: list[str]


def resolve_provider_git_options(
    git_provider: str | None,
    project_path: str,
    settings: Settings,
) -> ProviderGitOptions | None:
    if git_provider is None:
        return None

    normalized = git_provider.strip().lower()
    if normalized not in SUPPORTED_GIT_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_GIT_PROVIDERS))
        raise ValueError(f"Unsupported git provider: {git_provider}. Supported providers: {supported}")

    provider_settings = settings.get_provider_settings(normalized)
    return build_provider_git_options(
        project_path=project_path,
        provider_settings=provider_settings,
    )


def build_provider_git_options(
    project_path: str,
    provider_settings: ProviderSettings,
) -> ProviderGitOptions:
    if not provider_settings.base_url:
        raise ValueError(
            f"{provider_settings.provider} base URL is not configured. "
            "Update ~/.openpatch/config.json with gitProvider.baseUrl or set an environment override."
        )
    if not provider_settings.token:
        raise ValueError(
            f"{provider_settings.provider} token is not configured. "
            "Update ~/.openpatch/config.json with gitProvider.token or set an environment override."
        )

    clone_url = build_provider_clone_url(
        base_url=provider_settings.base_url,
        project_path=project_path,
    )
    git_config_args = build_provider_git_config_args(provider_settings)

    logger.info(
        "Prepared %s clone settings for project_path='%s'",
        provider_settings.provider,
        project_path,
    )
    return ProviderGitOptions(
        provider=provider_settings.provider,
        clone_url=clone_url,
        git_config_args=git_config_args,
    )


def build_provider_clone_url(base_url: str, project_path: str) -> str:
    normalized_project_path = project_path.strip("/")
    return f"{base_url.rstrip('/')}/{normalized_project_path}.git"


def build_provider_git_config_args(provider_settings: ProviderSettings) -> list[str]:
    if provider_settings.provider == "gitlab":
        return [
            "-c",
            f"http.{provider_settings.base_url}/.extraheader=Authorization: Bearer {provider_settings.token}",
        ]

    if provider_settings.provider == "github":
        encoded = base64.b64encode(
            f"x-access-token:{provider_settings.token}".encode("utf-8")
        ).decode("ascii")
        return [
            "-c",
            f"http.{provider_settings.base_url}/.extraheader=Authorization: Basic {encoded}",
        ]

    raise ValueError(f"Unsupported git provider: {provider_settings.provider}")
