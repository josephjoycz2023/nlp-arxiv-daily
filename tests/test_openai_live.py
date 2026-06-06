from __future__ import annotations

import os

import pytest

from nlp_arxiv_daily.openai_client import OpenAITextClient


pytestmark = pytest.mark.integration


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY is required for live API test")
def test_openai_structured_output_live_smoke():
    client = OpenAITextClient(
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        timeout=60,
    )

    payload = client.complete_json(
        "Return JSON with answer='ok' and nothing else.",
        schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        schema_name="live_smoke_answer",
    )

    assert payload["answer"].lower() == "ok"
