from openpatch_worker.schemas import AgentRunRequest, AgentRunResponse
from openpatch_worker.services.context_service import build_minimal_repo_context
from openpatch_worker.services.model_client import (
    ModelGenerationRequest,
    OpenAICompatibleModelClient,
)


def run_agent_task(request: AgentRunRequest) -> AgentRunResponse:
    context_summary, repo_context = build_minimal_repo_context(request.repo_path)
    client = OpenAICompatibleModelClient()

    system_prompt = (
        "You are OpenPatch, a coding assistant. "
        "Use the provided repository context to answer the user's task. "
        "Be explicit about uncertainty and do not assume access to files outside the provided context."
    )
    user_prompt = (
        f"Task:\n{request.task}\n\n"
        f"Repository context:\n{repo_context}"
    )

    response_text = client.generate_text(
        ModelGenerationRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
    )

    return AgentRunResponse(
        repo_path=request.repo_path,
        model=client.model_name,
        context_summary=context_summary,
        response=response_text,
    )
