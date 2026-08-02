import json

import httpx
import pytest
import respx

from opensource_scout.config import Settings
from opensource_scout.db.session import build_engine, build_session_factory, create_schema
from opensource_scout.domain.llm_models import ProjectAssessment
from opensource_scout.llm.cache import InMemoryLlmCache
from opensource_scout.llm.client import OpenAiClient
from opensource_scout.llm.errors import MalformedOutputError
from opensource_scout.llm.router import ModelRole


def _response_body(payload: dict, *, input_tokens: int = 50, output_tokens: int = 20) -> dict:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-4o-mini",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": json.dumps(payload), "annotations": []}
                ],
            }
        ],
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "input_tokens_details": {"cached_tokens": 0},
        },
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
    }


_VALID_PAYLOAD = {
    "career_relevance": 20,
    "technical_depth": 10,
    "evidence": ["strong overlap"],
    "risks": [],
    "explanation": "good fit",
}


@pytest.fixture
def session_factory():
    engine = build_engine("sqlite:///:memory:")
    create_schema(engine)
    try:
        yield build_session_factory(engine)
    finally:
        engine.dispose()


@pytest.mark.respx(base_url="https://api.openai.com")
async def test_structured_call_returns_parsed_model(
    respx_mock: respx.MockRouter, session_factory
) -> None:
    respx_mock.post("/v1/responses").mock(
        return_value=httpx.Response(200, json=_response_body(_VALID_PAYLOAD))
    )
    settings = Settings(OPENAI_MODEL_FAST="gpt-4o-mini")
    client = OpenAiClient(api_key="sk-test")
    try:
        result = await client.complete_structured(
            settings=settings,
            session_factory=session_factory,
            cache=InMemoryLlmCache(),
            role=ModelRole.FAST,
            task_category="project_classification",
            system="system prompt",
            user="user prompt",
            response_model=ProjectAssessment,
            calls_this_workflow=0,
        )
    finally:
        await client.aclose()

    assert result.career_relevance == 20
    assert result.explanation == "good fit"


@pytest.mark.respx(base_url="https://api.openai.com")
async def test_identical_call_is_served_from_cache(
    respx_mock: respx.MockRouter, session_factory
) -> None:
    route = respx_mock.post("/v1/responses").mock(
        return_value=httpx.Response(200, json=_response_body(_VALID_PAYLOAD))
    )
    settings = Settings(OPENAI_MODEL_FAST="gpt-4o-mini")
    cache = InMemoryLlmCache()
    client = OpenAiClient(api_key="sk-test")
    try:
        kwargs = {
            "settings": settings,
            "session_factory": session_factory,
            "cache": cache,
            "role": ModelRole.FAST,
            "task_category": "project_classification",
            "system": "system prompt",
            "user": "user prompt",
            "response_model": ProjectAssessment,
        }
        await client.complete_structured(calls_this_workflow=0, **kwargs)
        await client.complete_structured(calls_this_workflow=1, **kwargs)
    finally:
        await client.aclose()

    assert route.call_count == 1


@pytest.mark.respx(base_url="https://api.openai.com")
async def test_malformed_output_retries_once_then_raises(
    respx_mock: respx.MockRouter, session_factory
) -> None:
    route = respx_mock.post("/v1/responses").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "resp_x",
                "object": "response",
                "created_at": 0,
                "model": "gpt-4o-mini",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "m",
                        "status": "completed",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "not valid json", "annotations": []}
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 5,
                    "total_tokens": 10,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "input_tokens_details": {"cached_tokens": 0},
                },
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            },
        )
    )
    settings = Settings(OPENAI_MODEL_FAST="gpt-4o-mini")
    client = OpenAiClient(api_key="sk-test")
    try:
        with pytest.raises(MalformedOutputError):
            await client.complete_structured(
                settings=settings,
                session_factory=session_factory,
                cache=InMemoryLlmCache(),
                role=ModelRole.FAST,
                task_category="x",
                system="s",
                user="u",
                response_model=ProjectAssessment,
                calls_this_workflow=0,
            )
    finally:
        await client.aclose()

    assert route.call_count == 2  # original attempt + one retry


@pytest.mark.respx(base_url="https://api.openai.com")
async def test_records_call_metadata_not_raw_content(
    respx_mock: respx.MockRouter, session_factory
) -> None:
    from sqlalchemy import select

    from opensource_scout.db.models import LlmCallRow

    respx_mock.post("/v1/responses").mock(
        return_value=httpx.Response(200, json=_response_body(_VALID_PAYLOAD))
    )
    settings = Settings(OPENAI_MODEL_FAST="gpt-4o-mini")
    client = OpenAiClient(api_key="sk-test")
    try:
        await client.complete_structured(
            settings=settings,
            session_factory=session_factory,
            cache=InMemoryLlmCache(),
            role=ModelRole.FAST,
            task_category="project_classification",
            system="system prompt with secret info",
            user="user prompt",
            response_model=ProjectAssessment,
            calls_this_workflow=0,
        )
    finally:
        await client.aclose()

    with session_factory() as session:
        row = session.execute(select(LlmCallRow)).scalar_one()
        assert row.model == "gpt-4o-mini"
        assert row.task_category == "project_classification"
        assert row.input_tokens == 50
        assert row.output_tokens == 20
        assert row.estimated_cost_usd > 0
        assert row.cache_status == "MISS"
        # only a hash is stored, never the prompt text itself
        assert "secret info" not in row.prompt_hash
