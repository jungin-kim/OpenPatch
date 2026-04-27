from openpatch_worker.schemas import AgentRunRequest, AgentRunResponse
from openpatch_worker.services.context_service import build_minimal_repo_context
from openpatch_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)


def run_agent_task(request: AgentRunRequest) -> AgentRunResponse:
    repo_context = build_minimal_repo_context(request.project_path)
    client = OpenAICompatibleModelClient()

    system_prompt = (
        "You are OpenPatch, a read-only repository assistant. "
        "Use only the provided repository context to answer the user's task. "
        "Do not claim to have inspected files that are not included in the provided context. "
        "If the task would require more context, say what is missing and what to inspect next."
    )
    user_prompt = (
        f"Task:\n{request.task}\n\n"
        f"Repository context:\n{repo_context.prompt_context}"
    )

    response_text = client.generate_text(
        ModelGenerationRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    )

    return AgentRunResponse(
        project_path=request.project_path,
        task=request.task,
        model=client.model_name,
        branch=repo_context.branch,
        repo_root_name=repo_context.repo_root_name,
        context_summary=repo_context.summary,
        top_level_entries=repo_context.top_level_entries,
        readme_included=bool(repo_context.readme_excerpt),
        diff_included=bool(repo_context.diff_excerpt),
        response=response_text,
    )
