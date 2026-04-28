from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

from openpatch_worker.config import get_settings
from openpatch_worker.schemas import (
    ProviderBranchSummary,
    ProviderBranchesResponse,
    ProviderProjectSummary,
    ProviderProjectsResponse,
)
from openpatch_worker.services.common import get_openpatch_home_dir, is_git_repository
from openpatch_worker.services.subprocess_utils import run_subprocess

SUPPORTED_PROVIDER_LISTING = {"gitlab", "github", "local"}
RECENT_PROJECTS_FILE_NAME = "recent-projects.json"


def list_provider_projects(
    git_provider: str,
    search: str | None = None,
) -> ProviderProjectsResponse:
    normalized = _normalize_git_provider(git_provider)
    if normalized == "gitlab":
        projects = _list_gitlab_projects(search=search)
    elif normalized == "github":
        projects = _list_github_projects(search=search)
    else:
        projects = _list_local_projects(search=search)

    recent_projects = _build_recent_projects(
        git_provider=normalized,
        discovered_projects=projects,
    )

    return ProviderProjectsResponse(
        git_provider=normalized,
        configured_git_provider=get_settings().configured_git_provider,
        projects=projects,
        recent_projects=recent_projects,
    )


def list_provider_branches(
    git_provider: str,
    project_path: str,
) -> ProviderBranchesResponse:
    normalized = _normalize_git_provider(git_provider)
    if not project_path.strip():
        raise ValueError("project_path must not be empty")

    normalized_project_path = project_path if normalized == "local" else project_path.strip("/")

    if normalized == "gitlab":
        default_branch, branches = _list_gitlab_branches(normalized_project_path)
    elif normalized == "github":
        default_branch, branches = _list_github_branches(normalized_project_path)
    else:
        default_branch, branches = _list_local_branches(normalized_project_path)

    return ProviderBranchesResponse(
        git_provider=normalized,
        project_path=normalized_project_path,
        default_branch=default_branch,
        branches=branches,
    )


def record_recent_project(
    project_path: str,
    git_provider: str,
    display_name: str | None = None,
    is_git_repo: bool | None = None,
) -> None:
    normalized = _normalize_git_provider(git_provider)
    recent_projects = _load_recent_project_entries()
    normalized_project_path = project_path if normalized == "local" else project_path.strip("/")
    updated_entry = {
        "git_provider": normalized,
        "project_path": normalized_project_path,
        "display_name": display_name or Path(normalized_project_path).name or normalized_project_path,
        "is_git_repository": True if is_git_repo is None else is_git_repo,
        "last_opened_at": datetime.now(timezone.utc).isoformat(),
    }

    deduplicated = [
        entry
        for entry in recent_projects
        if not (
            entry.get("git_provider") == normalized
            and entry.get("project_path") == normalized_project_path
        )
    ]
    deduplicated.insert(0, updated_entry)
    _save_recent_project_entries(deduplicated[:20])


def list_recent_project_paths(limit: int = 8) -> list[str]:
    return [entry.project_path for entry in list_recent_projects(limit=limit)]


def list_recent_projects(
    limit: int = 8,
    git_provider: str | None = None,
) -> list[ProviderProjectSummary]:
    normalized_provider = _normalize_git_provider(git_provider) if git_provider else None
    recent_entries = _load_recent_project_entries()
    projects: list[ProviderProjectSummary] = []

    for entry in recent_entries:
        entry_provider = entry.get("git_provider")
        if normalized_provider and entry_provider != normalized_provider:
            continue
        project_path = entry.get("project_path")
        if not isinstance(project_path, str) or not project_path.strip():
            continue
        projects.append(
            ProviderProjectSummary(
                git_provider=entry_provider or "local",
                project_path=project_path,
                display_name=entry.get("display_name") or project_path,
                default_branch=None,
                source="recent",
                is_git_repository=bool(entry.get("is_git_repository", True)),
            )
        )
        if len(projects) >= limit:
            break

    return projects


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
            is_git_repository=True,
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
            is_git_repository=True,
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


def _list_local_projects(search: str | None) -> list[ProviderProjectSummary]:
    query = (search or "").strip()
    projects = list_recent_projects(limit=12, git_provider="local")

    if query:
        normalized_query = query.lower()
        projects = [
            project
            for project in projects
            if normalized_query in project.project_path.lower()
            or normalized_query in project.display_name.lower()
        ]

        candidate_path = Path(query).expanduser()
        if candidate_path.is_absolute() and candidate_path.exists() and candidate_path.is_dir():
            resolved = str(candidate_path.resolve())
            if all(project.project_path != resolved for project in projects):
                projects.insert(
                    0,
                    ProviderProjectSummary(
                        git_provider="local",
                        project_path=resolved,
                        display_name=candidate_path.name or resolved,
                        default_branch=_get_local_default_branch(resolved),
                        source="manual",
                        is_git_repository=is_git_repository(candidate_path.resolve()),
                    ),
                )

    return projects


def _list_local_branches(project_path: str) -> tuple[str | None, list[ProviderBranchSummary]]:
    repo_path = Path(project_path).expanduser().resolve()
    if not repo_path.exists():
        raise ValueError(f"Local project path does not exist: {repo_path}")
    if not repo_path.is_dir():
        raise ValueError(f"Local project path is not a directory: {repo_path}")
    if not is_git_repository(repo_path):
        return None, []

    current_branch = _safe_git_output(repo_path, ["git", "branch", "--show-current"]) or None
    output = _safe_git_output(
        repo_path,
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"],
    )
    branches = [
        ProviderBranchSummary(name=name, is_default=name == current_branch)
        for name in output.splitlines()
        if name.strip()
    ]
    return current_branch, branches


def _get_local_default_branch(project_path: str) -> str | None:
    default_branch, _ = _list_local_branches(project_path)
    return default_branch


def _build_recent_projects(
    git_provider: str,
    discovered_projects: list[ProviderProjectSummary],
) -> list[ProviderProjectSummary]:
    recent_paths = list_recent_projects(git_provider=git_provider)
    discovered_map = {project.project_path: project for project in discovered_projects}
    recent_projects: list[ProviderProjectSummary] = []

    for project in recent_paths:
        existing = discovered_map.get(project.project_path)
        if existing is not None:
            recent_projects.append(
                existing.model_copy(update={"source": "recent"})
            )
            continue
        recent_projects.append(project)

    return recent_projects


def _normalize_git_provider(git_provider: str) -> str:
    normalized = git_provider.strip().lower()
    if normalized not in SUPPORTED_PROVIDER_LISTING:
        raise ValueError("git_provider must be one of: gitlab, github, local")
    return normalized


def _recent_projects_file_path() -> Path:
    return get_openpatch_home_dir() / RECENT_PROJECTS_FILE_NAME


def _load_recent_project_entries() -> list[dict]:
    file_path = _recent_projects_file_path()
    if not file_path.exists():
        return []
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _save_recent_project_entries(entries: list[dict]) -> None:
    file_path = _recent_projects_file_path()
    file_path.write_text(
        json.dumps(entries, indent=2, sort_keys=True),
        encoding="utf-8",
    )


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
            "User-Agent": "RepoOperator local worker",
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


def _safe_git_output(repo_path: Path, command: list[str]) -> str:
    result = run_subprocess(command=command, cwd=repo_path, timeout_seconds=15)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()
