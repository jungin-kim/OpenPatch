import json
from dataclasses import dataclass
from urllib import error, parse, request

from repooperator_worker.config import Settings
from repooperator_worker.schemas import (
    GitMergeRequestCreateRequest,
    GitMergeRequestCreateResponse,
)


@dataclass(frozen=True)
class MergeRequestProviderContext:
    settings: Settings


def create_merge_request(
    request_payload: GitMergeRequestCreateRequest,
    context: MergeRequestProviderContext,
) -> GitMergeRequestCreateResponse:
    if request_payload.git_provider == "gitlab":
        return _create_gitlab_merge_request(request_payload, context)
    raise ValueError(f"Unsupported git provider: {request_payload.git_provider}")


def _create_gitlab_merge_request(
    request_payload: GitMergeRequestCreateRequest,
    context: MergeRequestProviderContext,
) -> GitMergeRequestCreateResponse:
    settings = context.settings
    provider_settings = settings.get_provider_settings("gitlab")
    if not provider_settings.base_url:
        raise ValueError(
            "gitlab base URL is not configured. Update ~/.repooperator/config.json with gitProvider.baseUrl or set an environment override."
        )
    if not provider_settings.token:
        raise ValueError(
            "gitlab token is not configured. Update ~/.repooperator/config.json with gitProvider.token or set an environment override."
        )

    encoded_project = parse.quote(request_payload.project_path, safe="")
    url = f"{provider_settings.base_url}/api/v4/projects/{encoded_project}/merge_requests"
    payload = {
        "source_branch": request_payload.source_branch,
        "target_branch": request_payload.target_branch,
        "title": request_payload.title,
    }
    if request_payload.description:
        payload["description"] = request_payload.description

    http_request = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "PRIVATE-TOKEN": provider_settings.token,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=30) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitLab merge request creation failed with status {exc.code}: {error_body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"GitLab API connection failed: {exc.reason}") from exc

    return GitMergeRequestCreateResponse(
        project_path=request_payload.project_path,
        git_provider=request_payload.git_provider,
        title=response_payload.get("title", request_payload.title),
        web_url=response_payload["web_url"],
        iid=str(response_payload["iid"]),
        state=response_payload.get("state", "unknown"),
    )
