from __future__ import annotations

import requests


OPENAI_RESPONSES_PATH = "/responses"


class OpenAIConfigError(ValueError):
    """Raised when required OpenAI settings are missing or invalid."""


class OpenAIResponseError(RuntimeError):
    """Raised when the OpenAI API response is missing assistant text."""


def _extract_output_text(payload: dict) -> str:
    parts: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text = content.get("text", "")
                if text:
                    parts.append(text)
    if parts:
        return "".join(parts).strip()
    raise OpenAIResponseError("OpenAI response did not contain any output_text content.")


class OpenAITextClient:
    """Small reusable wrapper around the OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout: int,
        instructions: str = "",
        session: requests.Session | None = None,
    ) -> None:
        api_key = api_key.strip()
        model = model.strip()
        if not api_key:
            raise OpenAIConfigError("openai_api_key is required.")
        if not model:
            raise OpenAIConfigError("openai_model is required.")

        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._instructions = instructions.strip()
        self._session = session or requests.Session()

    @classmethod
    def from_config(cls, config: dict) -> OpenAITextClient:
        return cls(
            api_key=config.get("openai_api_key", ""),
            model=config.get("openai_model", "gpt-5-mini"),
            base_url=config.get("openai_base_url", "https://api.openai.com/v1"),
            timeout=int(config.get("openai_timeout", 60)),
            instructions=config.get("openai_instructions", ""),
        )

    def complete(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty.")

        payload = {
            "model": self._model,
            "input": prompt,
        }
        if self._instructions:
            payload["instructions"] = self._instructions

        resp = self._session.post(
            f"{self._base_url}{OPENAI_RESPONSES_PATH}",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return _extract_output_text(resp.json())


def request_openai_text(prompt: str, config: dict) -> str:
    """One-shot convenience helper for callers that do not need client reuse."""
    return OpenAITextClient.from_config(config).complete(prompt)
