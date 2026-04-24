import logging
from dataclasses import dataclass

from openpatch_worker.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderGitOptions:
    clone_url: str
    git_config_args: list[str]


def resolve_provider_git_options(
    git_provider: str | None,
    project_path: str,
    settings: Settings,
) -> ProviderGitOptions | None:
    if git_provider is None:
        return None
    if git_provider == "gitlab":
        return build_gitlab_options(project_path=project_path, settings=settings)
    raise ValueError(f"Unsupported git provider: {git_provider}")


def build_gitlab_options(project_path: str, settings: Settings) -> ProviderGitOptions:
    if not settings.gitlab_base_url:
        raise ValueError(
            "GITLAB_BASE_URL is required when git_provider is 'gitlab'."
        )
    if not settings.gitlab_token:
        raise ValueError(
            "GITLAB_TOKEN is required when git_provider is 'gitlab'."
        )

    clone_url = build_gitlab_clone_url(
        base_url=settings.gitlab_base_url,
        project_path=project_path,
    )
    git_config_args = [
        "-c",
        f"http.{settings.gitlab_base_url}/.extraheader=Authorization: Bearer {settings.gitlab_token}",
    ]

    logger.info("Prepared GitLab clone settings for project_path='%s'", project_path)
    return ProviderGitOptions(clone_url=clone_url, git_config_args=git_config_args)


def build_gitlab_clone_url(base_url: str, project_path: str) -> str:
    normalized_project_path = project_path.strip("/")
    return f"{base_url.rstrip('/')}/{normalized_project_path}.git"
