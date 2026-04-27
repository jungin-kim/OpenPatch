import json
from dataclasses import dataclass
from urllib import error, request

from openpatch_worker.config import get_settings


@dataclass(frozen=True)
class ModelGenerationRequest:
    system_prompt: str
    user_prompt: str


class OpenAICompatibleModelClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def model_name(self) -> str:
        if not self._settings.openai_model:
            raise ValueError("OPENAI_MODEL is not configured.")
        return self._settings.openai_model

    def generate_text(self, prompt: ModelGenerationRequest) -> str:
        http_request = request.Request(
            url=self._chat_completions_url,
            data=json.dumps(self._build_payload(prompt)).encode("utf-8"),
            headers=self._build_headers(),
            method="POST",
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self._settings.model_request_timeout_seconds,
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Model API request failed with status {exc.code}: {error_body}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Model API connection failed: {exc.reason}") from exc

        response_text = _extract_response_text(response_payload).strip()
        if not response_text:
            raise RuntimeError("Model API response was empty.")
        return response_text

    @property
    def _chat_completions_url(self) -> str:
        base_url = self._settings.openai_base_url
        if not base_url:
            raise ValueError("OPENAI_BASE_URL is not configured.")
        return f"{base_url}/chat/completions"

    def _build_headers(self) -> dict[str, str]:
        api_key = self._settings.openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, prompt: ModelGenerationRequest) -> dict:
        return {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": prompt.user_prompt},
            ],
        }


def _extract_response_text(response_payload: dict) -> str:
    try:
        return response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Model API response did not contain a chat completion message.") from exc
