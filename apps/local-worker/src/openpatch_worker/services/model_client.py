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
        base_url = self._settings.openai_base_url
        api_key = self._settings.openai_api_key

        if not base_url:
            raise ValueError("OPENAI_BASE_URL is not configured.")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": prompt.system_prompt},
                {"role": "user", "content": prompt.user_prompt},
            ],
        }

        http_request = request.Request(
            url=f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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

        return _extract_response_text(response_payload)


def _extract_response_text(response_payload: dict) -> str:
    try:
        return response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Model API response did not contain a chat completion message.") from exc
