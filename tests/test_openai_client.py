import pytest
import requests

from nlp_arxiv_daily.openai_client import (
    OpenAIAllKeysFailedError,
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


class _FakeSessionByAuthorization:
    def __init__(self, responses_by_auth: dict[str, _FakeResponse]):
        self.calls: list[dict] = []
        self._responses_by_auth = responses_by_auth

    def post(self, url, headers, json, timeout):
        call = {
            "url": url,
            "headers": headers,
            "json": json,
            "timeout": timeout,
        }
        self.calls.append(call)
        return self._responses_by_auth[headers["Authorization"]]


class _FakeMessage:
    def __init__(self, content, reasoning_content: str = ""):
        self.content = content
        self.reasoning_content = reasoning_content


class _FakeChoice:
    def __init__(self, message: _FakeMessage):
        self.message = message


class _FakeChatCompletionResponse:
    def __init__(self, content, reasoning_content: str = ""):
        self.choices = [_FakeChoice(_FakeMessage(content, reasoning_content=reasoning_content))]


class _FakeCompletionsAPI:
    def __init__(self, response: _FakeChatCompletionResponse):
        self.calls: list[dict] = []
        self._response = response

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeDeepSeekSDKClient:
    def __init__(self, response: _FakeChatCompletionResponse):
        self.completions = _FakeCompletionsAPI(response)
        self.chat = type("_FakeChat", (), {"completions": self.completions})()


class TestOpenAITextClient:
    def test_requires_api_key(self):
        with pytest.raises(OpenAIConfigError):
            OpenAITextClient(
                api_key="",
                model="gpt-5-mini",
                base_url="https://api.openai.com/v1",
                timeout=60,
            )

    def test_requires_model(self):
        with pytest.raises(OpenAIConfigError):
            OpenAITextClient(
                api_key="test-key",
                model="",
                base_url="https://api.openai.com/v1",
                timeout=60,
            )

    def test_rejects_invalid_provider(self):
        with pytest.raises(OpenAIConfigError):
            OpenAITextClient(
                api_key="test-key",
                model="gpt-5-mini",
                base_url="https://api.openai.com/v1",
                timeout=60,
                provider="unknown",
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

    def test_openai_falls_back_to_next_api_key(self):
        session = _FakeSessionByAuthorization(
            {
                "Bearer bad-key": _FakeResponse({"error": "unauthorized"}, status_code=401),
                "Bearer good-key": _FakeResponse(
                    {
                        "output": [
                            {
                                "content": [
                                    {"type": "output_text", "text": "hello world"},
                                ]
                            }
                        ]
                    }
                ),
            }
        )
        client = OpenAITextClient(
            api_key="bad-key",
            api_keys=["bad-key", "good-key"],
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=42,
            session=session,
        )

        assert client.complete("say hi") == "hello world"
        assert [call["headers"]["Authorization"] for call in session.calls] == ["Bearer bad-key", "Bearer good-key"]

    def test_openai_raises_when_all_api_keys_fail(self):
        session = _FakeSessionByAuthorization(
            {
                "Bearer bad-key-1": _FakeResponse({"error": "unauthorized"}, status_code=401),
                "Bearer bad-key-2": _FakeResponse({"error": "unauthorized"}, status_code=401),
            }
        )
        client = OpenAITextClient(
            api_key="bad-key-1",
            api_keys=["bad-key-1", "bad-key-2"],
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=42,
            session=session,
        )

        with pytest.raises(OpenAIResponseError):
            client.complete("say hi")

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

    def test_raises_when_json_root_is_not_object(self):
        session = _FakeSession(
            _FakeResponse(
                {
                    "output": [
                        {
                            "content": [
                                {"type": "output_text", "text": '["ok"]'},
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

    def test_complete_rejects_empty_prompt(self):
        client = OpenAITextClient(
            api_key="test-key",
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=60,
        )

        with pytest.raises(ValueError):
            client.complete("   ")

    def test_complete_json_rejects_empty_prompt(self):
        client = OpenAITextClient(
            api_key="test-key",
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=60,
        )

        with pytest.raises(ValueError):
            client.complete_json(
                "   ",
                schema={"type": "object"},
                schema_name="answer_schema",
            )

    def test_complete_json_rejects_empty_schema_name(self):
        client = OpenAITextClient(
            api_key="test-key",
            model="gpt-5-mini",
            base_url="https://api.openai.com/v1",
            timeout=60,
        )

        with pytest.raises(ValueError):
            client.complete_json(
                "return json",
                schema={"type": "object"},
                schema_name="   ",
            )

    def test_deepseek_complete_uses_chat_completions(self):
        sdk_client = _FakeDeepSeekSDKClient(
            _FakeChatCompletionResponse("hello from deepseek", reasoning_content="hidden thinking")
        )
        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            instructions="be concise",
            provider="deepseek",
            reasoning_effort="high",
            thinking_enabled=True,
            sdk_client=sdk_client,
        )

        text = client.complete("say hi")

        assert text == "hello from deepseek"
        assert sdk_client.completions.calls == [
            {
                "model": "deepseek-v4-pro",
                "messages": [
                    {"role": "system", "content": "be concise"},
                    {"role": "user", "content": "say hi"},
                ],
                "reasoning_effort": "high",
                "extra_body": {"thinking": {"type": "enabled"}},
            }
        ]

    def test_deepseek_falls_back_to_next_api_key(self, monkeypatch):
        clients = {
            "bad-key": _FakeDeepSeekSDKClient(_FakeChatCompletionResponse("unused")),
            "good-key": _FakeDeepSeekSDKClient(_FakeChatCompletionResponse("hello from deepseek")),
        }

        class _RetryableDeepSeekError(Exception):
            pass

        def build_client(self, *, api_key=None):
            client = clients[api_key]
            if api_key == "bad-key":
                def raise_auth(**kwargs):
                    raise _RetryableDeepSeekError("bad key")

                client.completions.create = raise_auth
            return client

        monkeypatch.setattr(OpenAITextClient, "_build_deepseek_sdk_client", build_client)
        monkeypatch.setattr(
            "nlp_arxiv_daily.openai_client._should_failover_deepseek_error",
            lambda error: isinstance(error, _RetryableDeepSeekError),
        )
        client = OpenAITextClient(
            api_key="bad-key",
            api_keys=["bad-key", "good-key"],
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
        )

        assert client.complete("say hi") == "hello from deepseek"
        assert clients["good-key"].completions.calls[0]["messages"] == [{"role": "user", "content": "say hi"}]

    def test_deepseek_retries_same_key_for_transient_error(self, monkeypatch):
        client_instance = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse("hello from deepseek"))
        attempts = {"count": 0}

        class _TransientDeepSeekError(Exception):
            pass

        def create(**kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise _TransientDeepSeekError("connection dropped")
            client_instance.completions.calls.append(kwargs)
            return client_instance.completions._response

        client_instance.completions.create = create
        monkeypatch.setattr(OpenAITextClient, "_build_deepseek_sdk_client", lambda self, *, api_key=None: client_instance)
        monkeypatch.setattr(
            "nlp_arxiv_daily.openai_client._should_failover_deepseek_error",
            lambda error: isinstance(error, _TransientDeepSeekError),
        )
        monkeypatch.setattr(
            "nlp_arxiv_daily.openai_client._should_retry_deepseek_error",
            lambda error: isinstance(error, _TransientDeepSeekError),
        )

        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
            request_retries=1,
        )

        assert client.complete("say hi") == "hello from deepseek"
        assert attempts["count"] == 2

    def test_deepseek_all_keys_failed_error_marks_transient_failures_retryable(self, monkeypatch):
        class _TransientDeepSeekError(Exception):
            pass

        client_instance = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse("unused"))
        monkeypatch.setattr(OpenAITextClient, "_build_deepseek_sdk_client", lambda self, *, api_key=None: client_instance)
        monkeypatch.setattr(
            "nlp_arxiv_daily.openai_client._should_failover_deepseek_error",
            lambda error: isinstance(error, _TransientDeepSeekError),
        )
        monkeypatch.setattr(
            "nlp_arxiv_daily.openai_client._should_retry_deepseek_error",
            lambda error: isinstance(error, _TransientDeepSeekError),
        )
        client_instance.completions.create = lambda **kwargs: (_ for _ in ()).throw(_TransientDeepSeekError("connection dropped"))

        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
            request_retries=0,
        )

        with pytest.raises(OpenAIAllKeysFailedError) as excinfo:
            client.complete("say hi")

        assert excinfo.value.retryable is True

    def test_deepseek_complete_json_requests_json_object(self):
        sdk_client = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse('{"answer":"ok"}'))
        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
            reasoning_effort="high",
            thinking_enabled=True,
            sdk_client=sdk_client,
        )

        payload = client.complete_json(
            "return json",
            schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
            schema_name="answer_schema",
            schema_description="Answer payload.",
        )

        assert payload == {"answer": "ok"}
        assert sdk_client.completions.calls[0]["response_format"] == {"type": "json_object"}
        assert "Follow this JSON Schema strictly:" in sdk_client.completions.calls[0]["messages"][0]["content"]

    def test_deepseek_complete_supports_list_content(self):
        content = [
            {"text": "hello "},
            type("_Chunk", (), {"text": "world"})(),
        ]
        sdk_client = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse(content))
        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
            sdk_client=sdk_client,
        )

        assert client.complete("say hi") == "hello world"

    def test_deepseek_complete_json_raises_when_json_response_is_invalid(self):
        sdk_client = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse("not json"))
        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
            sdk_client=sdk_client,
        )

        with pytest.raises(OpenAIResponseError):
            client.complete_json(
                "return json",
                schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
                schema_name="answer_schema",
            )

    def test_deepseek_complete_json_raises_when_json_root_is_not_object(self):
        sdk_client = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse('["ok"]'))
        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
            sdk_client=sdk_client,
        )

        with pytest.raises(OpenAIResponseError):
            client.complete_json(
                "return json",
                schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
                schema_name="answer_schema",
            )

    def test_deepseek_complete_raises_when_message_has_no_text(self):
        sdk_client = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse([]))
        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
            sdk_client=sdk_client,
        )

        with pytest.raises(OpenAIResponseError):
            client.complete("say hi")

    def test_deepseek_can_disable_reasoning_fields(self):
        sdk_client = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse("plain response"))
        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
            reasoning_effort="",
            thinking_enabled="false",
            sdk_client=sdk_client,
        )

        assert client.complete("say hi") == "plain response"
        assert sdk_client.completions.calls[0] == {
            "model": "deepseek-v4-pro",
            "messages": [{"role": "user", "content": "say hi"}],
        }

    def test_builds_deepseek_sdk_client(self):
        client = OpenAITextClient(
            api_key="deepseek-key",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
            timeout=45,
            provider="deepseek",
        )

        sdk_client = client._build_deepseek_sdk_client()

        assert sdk_client is not None

    def test_from_config_builds_deepseek_client(self):
        client = OpenAITextClient.from_config(
            {
                "llm_provider": "deepseek",
                "deepseek_api_key": "deepseek-key",
                "deepseek_model": "deepseek-v4-pro",
                "deepseek_base_url": "https://api.deepseek.com",
                "deepseek_timeout": 45,
                "deepseek_instructions": "be concise",
                "deepseek_reasoning_effort": "high",
                "deepseek_thinking_enabled": "true",
            }
        )

        assert client._provider == "deepseek"
        assert client._model == "deepseek-v4-pro"
        assert client._thinking_enabled is True

    def test_from_config_missing_key_message_points_to_local_config(self):
        with pytest.raises(OpenAIConfigError) as excinfo:
            OpenAITextClient.from_config(
                {
                    "llm_provider": "deepseek",
                    "deepseek_api_key": "",
                    "deepseek_api_keys": [],
                    "config_local_path": "C:/repo/config.local.yaml",
                }
            )

        assert "config.local.yaml" in str(excinfo.value)
        assert "DEEPSEEK_API_KEY" in str(excinfo.value)

    def test_from_config_falls_back_to_deepseek_when_openai_has_no_key(self):
        client = OpenAITextClient.from_config(
            {
                "llm_provider": "openai",
                "openai_api_key": "",
                "openai_api_keys": [],
                "openai_model": "gpt-5-mini",
                "openai_base_url": "https://api.openai.com/v1",
                "openai_timeout": 45,
                "openai_instructions": "",
                "deepseek_api_key": "deepseek-key",
                "deepseek_api_keys": [],
                "deepseek_model": "deepseek-v4-pro",
                "deepseek_base_url": "https://api.deepseek.com",
                "deepseek_timeout": 45,
                "deepseek_instructions": "",
                "deepseek_reasoning_effort": "high",
                "deepseek_thinking_enabled": True,
            }
        )

        assert client._provider == "deepseek"
        assert client._api_keys == ["deepseek-key"]

    def test_from_config_auto_prefers_deepseek_when_available(self):
        client = OpenAITextClient.from_config(
            {
                "llm_provider": "auto",
                "openai_api_key": "openai-key",
                "deepseek_api_key": "deepseek-key",
                "deepseek_model": "deepseek-v4-pro",
                "deepseek_base_url": "https://api.deepseek.com",
                "deepseek_timeout": 45,
                "deepseek_instructions": "",
                "deepseek_reasoning_effort": "high",
                "deepseek_thinking_enabled": True,
            }
        )

        assert client._provider == "deepseek"

    def test_from_config_builds_openai_client_with_multiple_keys(self):
        client = OpenAITextClient.from_config(
            {
                "llm_provider": "openai",
                "openai_api_key": "key-1",
                "openai_api_keys": ["key-1", "key-2"],
                "openai_model": "gpt-5-mini",
                "openai_base_url": "https://api.openai.com/v1",
                "openai_timeout": 45,
                "openai_instructions": "",
            }
        )

        assert client._provider == "openai"
        assert client._api_keys == ["key-1", "key-2"]

    def test_from_config_uses_analysis_timeout_for_openai_when_provider_timeout_missing(self):
        client = OpenAITextClient.from_config(
            {
                "llm_provider": "openai",
                "openai_api_key": "openai-key",
                "openai_model": "gpt-5-mini",
                "openai_base_url": "https://api.openai.com/v1",
                "analysis_request_timeout_seconds": 37,
                "openai_instructions": "",
            }
        )

        assert client._provider == "openai"
        assert client._timeout == 37

    def test_from_config_uses_analysis_timeout_for_deepseek_when_provider_timeout_missing(self):
        client = OpenAITextClient.from_config(
            {
                "llm_provider": "deepseek",
                "deepseek_api_key": "deepseek-key",
                "deepseek_model": "deepseek-v4-pro",
                "deepseek_base_url": "https://api.deepseek.com",
                "analysis_request_timeout_seconds": 37,
                "deepseek_instructions": "",
                "deepseek_reasoning_effort": "high",
                "deepseek_thinking_enabled": True,
            }
        )

        assert client._provider == "deepseek"
        assert client._timeout == 37


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

    def test_one_shot_helper_uses_deepseek_config(self, monkeypatch):
        sdk_client = _FakeDeepSeekSDKClient(_FakeChatCompletionResponse("done"))
        monkeypatch.setattr(
            OpenAITextClient,
            "_build_deepseek_sdk_client",
            lambda self, *, api_key=None: sdk_client,
        )

        text = request_openai_text(
            "prompt",
            {
                "llm_provider": "deepseek",
                "deepseek_api_key": "cfg-key",
                "deepseek_model": "deepseek-v4-pro",
                "deepseek_base_url": "https://api.deepseek.com",
                "deepseek_timeout": 30,
                "deepseek_instructions": "",
                "deepseek_reasoning_effort": "high",
                "deepseek_thinking_enabled": True,
            },
        )

        assert text == "done"
        assert sdk_client.completions.calls[0]["messages"][0]["content"] == "prompt"
