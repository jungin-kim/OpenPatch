from __future__ import annotations

import json
from pathlib import Path
from urllib import parse, request, error

from openpatch_worker.config import get_settings
from openpatch_worker.schemas import (
    ProviderBranchSummary,
    ProviderBranchesResponse,
    ProviderProjectSummary,
    ProviderProjectsResponse,
)


def list_provider_projects(
    git_provider: str,
    search: str | None = None,
) -> ProviderProjectsResponse:
    settings = get_settings()
    normalized = git_provider.strip().lower()
    if normalized not in {"gitlab", "github"}:
        raise ValueError("git_provider must be one of: gitlab, github")

    projects = (
        _list_gitlab_projects(search=search)
        if normalized == "gitlab"
        else _list_github_projects(search=search)
    )
    recent_projects = _build_recent_projects(
        git_provider=normalized,
        discovered_projects=projects,
    )

    return ProviderProjectsResponse(
        git_provider=normalized,
        configured_git_provider=_get_configured_git_provider(settings),
        projects=projects,
        recent_projects=recent_projects,
    )


def list_provider_branches(
    git_provider: str,
    project_path: str,
) -> ProviderBranchesResponse:
    normalized = git_provider.strip().lower()
    if normalized not in {"gitlab", "github"}:
        raise ValueError("git_provider must be one of: gitlab, github")
    if not project_path.strip():
        raise ValueError("project_path must not be empty")

    if normalized == "gitlab":
        default_branch, branches = _list_gitlab_branches(project_path.strip("/"))
    else:
        default_branch, branches = _list_github_branches(project_path.strip("/"))

    return ProviderBranchesResponse(
        git_provider=normalized,
        project_path=project_path.strip("/"),
        default_branch=default_branch,
        branches=branches,
    )


def list_recent_project_paths(limit: int = 8) -> list[str]:
    settings = get_settings()
    repo_base_dir = settings.repo_base_dir
    if not repo_base_dir.exists():
        return []

    discovered: list[tuple[float, str]] = []
    for git_dir in repo_base_dir.rglob(".git"):
        repo_root = git_dir.parent
        try:
            relative = repo_root.relative_to(repo_base_dir)
        except ValueError:
            continue
        discovered.append((repo_root.stat().st_mtime, relative.as_posix()))

    discovered.sort(key=lambda item: item[0], reverse=True)
    return [project_path for _, project_path in discovered[:limit]]


def _list_gitlab_projects(search: str | None) -> list[ProviderProjectSummary]:
    settings = get_settings()
    provider_settings = settings.get_provider_settings("gitlab")
    if not provider_settings.base_url:
        raise ValueError("gitlab base URL is not configured.")
    if not provider_settings.token:
        raise ValueError("gitlab token is not configured.")

    query = {
        "membership": "true",
        "simple": "true",
        "order_by": "last_activity_at",
        "sort": "desc",
        "per_page": "100",
    }
    if search and search.strip():
        query["search"] = search.strip()

    api_base = _build_gitlab_api_base(provider_settings.base_url)
    payload = _request_provider_json(
        url=f"{api_base}/projects?{parse.urlencode(query)}",
        headers={"PRIVATE-TOKEN": provider_settings.token},
        provider="gitlab",
    )

    return [
        ProviderProjectSummary(
            git_provider="gitlab",
            project_path=item["path_with_namespace"],
            display_name=item.get("name_with_namespace") or item["path_with_namespace"],
            default_branch=item.get("default_branch"),
            source="provider",
        )
        for item in payload
        if isinstance(item, dict) and item.get("path_with_namespace")
    ]


def _list_gitlab_branches(project_path: str) -> tuple[str | None, list[ProviderBranchSummary]]:
    settings = get_settings()
    provider_settings = settings.get_provider_settings("gitlab")
    if not provider_settings.base_url:
        raise ValueError("gitlab base URL is not configured.")
    if not provider_settings.token:
        raise ValueError("gitlab token is not configured.")

    api_base = _build_gitlab_api_base(provider_settings.base_url)
    encoded_project = parse.quote(project_path, safe="")
    payload = _request_provider_json(
        url=f"{api_base}/projects/{encoded_project}/repository/branches?per_page=100",
        headers={"PRIVATE-TOKEN": provider_settings.token},
        provider="gitlab",
    )

    branches = [
        ProviderBranchSummary(
            name=item["name"],
            is_default=bool(item.get("default")),
        )
        for item in payload
        if isinstance(item, dict) and item.get("name")
    ]
    default_branch = next((branch.name for branch in branches if branch.is_default), None)
    return default_branch, branches


def _list_github_projects(search: str | None) -> list[ProviderProjectSummary]:
    settings = get_settings()
    provider_settings = settings.get_provider_settings("github")
    if not provider_settings.base_url:
        raise ValueError("github base URL is not configured.")
    if not provider_settings.token:
        raise ValueError("github token is not configured.")

    api_base = _build_github_api_base(provider_settings.base_url)
    payload = _request_provider_json(
        url=f"{api_base}/user/repos?sort=updated&per_page=100",
        headers=_build_github_headers(provider_settings.token),
        provider="github",
    )

    projects = [
        ProviderProjectSummary(
            git_provider="github",
            project_path=item["full_name"],
            display_name=item.get("full_name") or item["name"],
            default_branch=item.get("default_branch"),
            source="provider",
        )
        for item in payload
        if isinstance(item, dict) and item.get("full_name")
    ]
    if search and search.strip():
        query = search.strip().lower()
        projects = [
            project
            for project in projects
            if query in project.project_path.lower() or query in project.display_name.lower()
        ]
    return projects


def _list_github_branches(project_path: str) -> tuple[str | None, list[ProviderBranchSummary]]:
    settings = get_settings()
    provider_settings = settings.get_provider_settings("github")
    if not provider_settings.base_url:
        raise ValueError("github base URL is not configured.")
    if not provider_settings.token:
        raise ValueError("github token is not configured.")

    api_base = _build_github_api_base(provider_settings.base_url)
    repo_payload = _request_provider_json(
        url=f"{api_base}/repos/{project_path}",
        headers=_build_github_headers(provider_settings.token),
        provider="github",
    )
    default_branch = repo_payload.get("default_branch") if isinstance(repo_payload, dict) else None
    branch_payload = _request_provider_json(
        url=f"{api_base}/repos/{project_path}/branches?per_page=100",
        headers=_build_github_headers(provider_settings.token),
        provider="github",
    )

    branches = [
        ProviderBranchSummary(
            name=item["name"],
            is_default=item.get("name") == default_branch,
        )
        for item in branch_payload
        if isinstance(item, dict) and item.get("name")
    ]
    return default_branch, branches


def _build_recent_projects(
    git_provider: str,
    discovered_projects: list[ProviderProjectSummary],
) -> list[ProviderProjectSummary]:
    recent_paths = list_recent_project_paths()
    discovered_map = {project.project_path: project for project in discovered_projects}
    recent_projects: list[ProviderProjectSummary] = []

    for project_path in recent_paths:
        existing = discovered_map.get(project_path)
        if existing is not None:
            recent_projects.append(
                existing.model_copy(update={"source": "recent"})
            )
            continue

        if discovered_projects:
            continue

        recent_projects.append(
            ProviderProjectSummary(
                git_provider=git_provider,
                project_path=project_path,
                display_name=project_path,
                default_branch=None,
                source="recent",
            )
        )

    return recent_projects


def _get_configured_git_provider(settings) -> str | None:
    if settings.gitlab_base_url and settings.gitlab_token:
        return "gitlab"
    if settings.github_base_url and settings.github_token:
        return "github"
    return None


def _build_gitlab_api_base(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v4"


def _build_github_api_base(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = parse.urlparse(normalized)
    if parsed.netloc.lower() in {"github.com", "www.github.com"}:
        return "https://api.github.com"
    return f"{normalized}/api/v3"


def _build_github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _request_provider_json(
    url: str,
    headers: dict[str, str],
    provider: str,
):
    request_object = request.Request(
        url,
        headers={
            "User-Agent": "OpenPatch local worker",
            **headers,
        },
    )
    try:
        with request.urlopen(request_object, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{provider} provider request failed with status {exc.code}: {message}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"Unable to reach the configured {provider} provider API: {exc.reason}"
        ) from exc
