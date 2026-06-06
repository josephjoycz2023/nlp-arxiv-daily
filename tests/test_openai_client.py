import pytest
import requests

from nlp_arxiv_daily.openai_client import (
    OpenAIConfigError,
    OpenAIResponseError,
    OpenAITextClient,
    request_openai_json,
    request_openai_text,
)


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.calls: list[dict] = []
        self._response = response

    def post(self, url, headers, json, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self._response


class TestOpenAITextClient:
    def test_requires_api_key(self):
        with pytest.raises(OpenAIConfigError):
            OpenAITextClient(
                api_key="",
                model="gpt-5-mini",
                base_url="https://api.openai.com/v1",
                timeout=60,
            )

    def test_posts_prompt_and_returns_output_text(self):
        session = _FakeSession(
            _FakeResponse(
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "hello world"},
                            ]
                        }
                    ]
                }
            )
        )
        client = OpenAITextClient(
            api_key="test-key",
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=42,
            instructions="be concise",
            session=session,
        )

        text = client.complete("say hi")

        assert text == "hello world"
        assert session.calls == [
            {
                "url": "https://api.openai.com/v1/responses",
                "headers": {
                    "Authorization": "Bearer test-key",
                    "Content-Type": "application/json",
                },
                "json": {
                    "model": "gpt-5-mini",
                    "input": "say hi",
                    "instructions": "be concise",
                },
                "timeout": 42,
            }
        ]

    def test_raises_when_output_text_missing(self):
        session = _FakeSession(_FakeResponse({"output": [{"content": [{"type": "refusal", "text": "no"}]}]}))
        client = OpenAITextClient(
            api_key="test-key",
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=60,
            session=session,
        )

        with pytest.raises(OpenAIResponseError):
            client.complete("say hi")

    def test_posts_json_schema_and_parses_json(self):
        session = _FakeSession(
            _FakeResponse(
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": '{"answer":"ok"}'},
                            ]
                        }
                    ]
                }
            )
        )
        client = OpenAITextClient(
            api_key="test-key",
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=60,
            session=session,
        )

        payload = client.complete_json(
            "return json",
            schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
            schema_name="answer_schema",
        )

        assert payload == {"answer": "ok"}
        assert session.calls[0]["json"]["format"] == {
            "type": "json_schema",
            "name": "answer_schema",
            "schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
            "strict": True,
        }

    def test_raises_when_json_response_is_invalid(self):
        session = _FakeSession(
            _FakeResponse(
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "not json"},
                            ]
                        }
                    ]
                }
            )
        )
        client = OpenAITextClient(
            api_key="test-key",
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=60,
            session=session,
        )

        with pytest.raises(OpenAIResponseError):
            client.complete_json(
                "return json",
                schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
                schema_name="answer_schema",
            )


class TestRequestOpenAIText:
    def test_one_shot_helper_uses_config(self, monkeypatch):
        session = _FakeSession(
            _FakeResponse(
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": "done"},
                            ]
                        }
                    ]
                }
            )
        )

        monkeypatch.setattr("nlp_arxiv_daily.openai_client.requests.Session", lambda: session)

        text = request_openai_text(
            "prompt",
            {
                "openai_api_key": "cfg-key",
                "openai_model": "gpt-5-mini",
                "openai_base_url": "https://api.openai.com/v1",
                "openai_timeout": 30,
                "openai_instructions": "",
            },
        )

        assert text == "done"
        assert session.calls[0]["json"]["input"] == "prompt"

    def test_one_shot_json_helper_uses_config(self, monkeypatch):
        session = _FakeSession(
            _FakeResponse(
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": '{"answer":"done"}'},
                            ]
                        }
                    ]
                }
            )
        )

        monkeypatch.setattr("nlp_arxiv_daily.openai_client.requests.Session", lambda: session)

        payload = request_openai_json(
            "prompt",
            {
                "openai_api_key": "cfg-key",
                "openai_model": "gpt-5-mini",
                "openai_base_url": "https://api.openai.com/v1",
                "openai_timeout": 30,
                "openai_instructions": "",
            },
            schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
            schema_name="answer_schema",
        )

        assert payload == {"answer": "done"}
        assert session.calls[0]["json"]["input"] == "prompt"
