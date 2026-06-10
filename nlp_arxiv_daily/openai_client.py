from __future__ import annotations

import json
from typing import Any

import requests


OPENAI_RESPONSES_PATH = "/responses"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class OpenAIConfigError(ValueError):
    """Raised when required OpenAI settings are missing or invalid."""


class OpenAIResponseError(RuntimeError):
    """Raised when the OpenAI API response is missing assistant text."""


def _extract_output_text(payload: dict) -> str:
    parts: list[str] = []
    refusals: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text = content.get("text", "")
                if text:
                    parts.append(text)
            if content.get("type") == "refusal":
                refusal_text = content.get("text", "")
                if refusal_text:
                    refusals.append(refusal_text)
    if parts:
        return "".join(parts).strip()
    if refusals:
        raise OpenAIResponseError(f"OpenAI response was a refusal: {' '.join(refusals).strip()}")
    raise OpenAIResponseError("OpenAI response did not contain any output_text content.")


def _normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in {"openai", "deepseek"}:
        raise OpenAIConfigError("llm_provider must be either 'openai' or 'deepseek'.")
    return normalized


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _extract_chat_message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = str(item.get("text", ""))
                if text.strip():
                    parts.append(text)
            else:
                text = str(getattr(item, "text", ""))
                if text.strip():
                    parts.append(text)
        if parts:
            return "".join(parts).strip()
    raise OpenAIResponseError("DeepSeek response did not contain any assistant text.")


def _build_deepseek_json_prompt(
    prompt: str,
    *,
    schema: dict,
    schema_name: str,
    schema_description: str = "",
) -> str:
    instructions = [
        prompt.strip(),
        "",
        f"Return exactly one JSON object for schema `{schema_name}`.",
        "Do not wrap the JSON in markdown fences.",
    ]
    if schema_description.strip():
        instructions.append(f"Schema description: {schema_description.strip()}")
    instructions.extend(
        [
            "Follow this JSON Schema strictly:",
            json.dumps(schema, ensure_ascii=False, indent=2),
        ]
    )
    return "\n".join(instructions).strip()


class OpenAITextClient:
    """Reusable wrapper around OpenAI Responses API and DeepSeek Chat Completions."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout: int,
        instructions: str = "",
        session: requests.Session | None = None,
        provider: str = "openai",
        reasoning_effort: str = "high",
        thinking_enabled: bool = True,
        sdk_client: Any | None = None,
    ) -> None:
        provider = _normalize_provider(provider)
        api_key = api_key.strip()
        model = model.strip()
        if not api_key:
            key_name = "deepseek_api_key" if provider == "deepseek" else "openai_api_key"
            raise OpenAIConfigError(f"{key_name} is required.")
        if not model:
            model_name = "deepseek_model" if provider == "deepseek" else "openai_model"
            raise OpenAIConfigError(f"{model_name} is required.")

        self._provider = provider
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._instructions = instructions.strip()
        self._session = session or requests.Session()
        self._reasoning_effort = reasoning_effort.strip()
        self._thinking_enabled = _as_bool(thinking_enabled)
        self._sdk_client = sdk_client

    @classmethod
    def from_config(cls, config: dict) -> OpenAITextClient:
        provider = _normalize_provider(config.get("llm_provider", "openai"))
        if provider == "deepseek":
            return cls(
                api_key=config.get("deepseek_api_key", ""),
                model=config.get("deepseek_model", "deepseek-v4-pro"),
                base_url=config.get("deepseek_base_url", DEEPSEEK_BASE_URL),
                timeout=int(config.get("deepseek_timeout", 60)),
                instructions=config.get("deepseek_instructions", ""),
                provider=provider,
                reasoning_effort=config.get("deepseek_reasoning_effort", "high"),
                thinking_enabled=config.get("deepseek_thinking_enabled", True),
            )
        return cls(
            api_key=config.get("openai_api_key", ""),
            model=config.get("openai_model", "gpt-5-mini"),
            base_url=config.get("openai_base_url", "https://api.openai.com/v1"),
            timeout=int(config.get("openai_timeout", 60)),
            instructions=config.get("openai_instructions", ""),
            provider=provider,
        )

    def complete(self, prompt: str) -> str:
        if not prompt.strip():
            raise ValueError("prompt must not be empty.")

        if self._provider == "deepseek":
            return self._complete_deepseek(prompt)

        payload = {
            "model": self._model,
            "input": prompt,
        }
        if self._instructions:
            payload["instructions"] = self._instructions

        return self._post(payload)

    def complete_json(
        self,
        prompt: str,
        *,
        schema: dict,
        schema_name: str,
        schema_description: str = "",
        strict: bool = True,
    ) -> dict:
        if not prompt.strip():
            raise ValueError("prompt must not be empty.")
        if not schema_name.strip():
            raise ValueError("schema_name must not be empty.")

        if self._provider == "deepseek":
            raw_text = self._complete_deepseek(
                _build_deepseek_json_prompt(
                    prompt,
                    schema=schema,
                    schema_name=schema_name,
                    schema_description=schema_description,
                ),
                response_format={"type": "json_object"},
            )
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError as e:
                raise OpenAIResponseError("DeepSeek response did not contain valid JSON.") from e
            if not isinstance(parsed, dict):
                raise OpenAIResponseError("DeepSeek response JSON root must be an object.")
            return parsed

        payload = {
            "model": self._model,
            "input": prompt,
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": strict,
            },
        }
        if schema_description.strip():
            payload["format"]["description"] = schema_description.strip()
        if self._instructions:
            payload["instructions"] = self._instructions

        raw_text = self._post(payload)
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as e:
            raise OpenAIResponseError("OpenAI response did not contain valid JSON.") from e
        if not isinstance(parsed, dict):
            raise OpenAIResponseError("OpenAI response JSON root must be an object.")
        return parsed

    def _post(self, payload: dict) -> str:

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

    def _complete_deepseek(self, prompt: str, *, response_format: dict | None = None) -> str:
        client = self._sdk_client or self._build_deepseek_sdk_client()
        self._sdk_client = client

        messages: list[dict[str, str]] = []
        if self._instructions:
            messages.append({"role": "system", "content": self._instructions})
        messages.append({"role": "user", "content": prompt})

        request_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }
        if self._reasoning_effort:
            request_kwargs["reasoning_effort"] = self._reasoning_effort
        if self._thinking_enabled:
            request_kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        if response_format is not None:
            request_kwargs["response_format"] = response_format

        response = client.chat.completions.create(**request_kwargs)
        return _extract_chat_message_text(response.choices[0].message)

    def _build_deepseek_sdk_client(self) -> Any:
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover - exercised only when dependency is missing at runtime.
            raise OpenAIConfigError(
                "The `openai` package is required for DeepSeek support. Run `uv sync` to install it."
            ) from e
        return OpenAI(
            api_key=self._api_key,
            base_url=self._base_url or DEEPSEEK_BASE_URL,
            timeout=self._timeout,
        )


def request_openai_text(prompt: str, config: dict) -> str:
    """One-shot convenience helper for callers that do not need client reuse."""
    return OpenAITextClient.from_config(config).complete(prompt)


def request_openai_json(
    prompt: str,
    config: dict,
    *,
    schema: dict,
    schema_name: str,
    schema_description: str = "",
    strict: bool = True,
) -> dict:
    """One-shot JSON helper for callers that want schema-validated model output."""
    return OpenAITextClient.from_config(config).complete_json(
        prompt,
        schema=schema,
        schema_name=schema_name,
        schema_description=schema_description,
        strict=strict,
    )
