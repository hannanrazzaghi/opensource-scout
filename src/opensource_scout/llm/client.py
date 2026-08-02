"""OpenAI Responses API client: structured outputs, caching, budget
enforcement, and per-call cost/usage recording — the single place every
programmatic LLM call in the project goes through.

Deliberately not a general-purpose chat wrapper: every call requires a
Pydantic ``response_model``, a task category (for cost breakdown and
routing decisions), and an explicit :class:`~opensource_scout.llm.router.ModelRole`.
There is no "just ask the model something" escape hatch — see
docs/architecture.md for why: an LLM call with no structured shape can't be
validated, and an unvalidated LLM output is not trusted anywhere in this
project.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TypeVar

import httpx
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from opensource_scout.config import Settings
from opensource_scout.db.models import LlmCallRow
from opensource_scout.llm import budget
from opensource_scout.llm.cache import LlmCache, compute_cache_key
from opensource_scout.llm.errors import LlmApiError, MalformedOutputError
from opensource_scout.llm.pricing import estimate_cost_usd
from opensource_scout.llm.router import ModelRole, resolve_model
from opensource_scout.logging import get_logger

logger = get_logger("llm.client")

T = TypeVar("T", bound=BaseModel)

# Rough estimate for pre-flight budget/size checks, before the API tells us
# the real count. Good enough to reject obviously-oversized requests early;
# never used for the cost actually recorded.
_CHARS_PER_TOKEN_ESTIMATE = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


class OpenAiClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key or "unset", http_client=http_client)

    async def aclose(self) -> None:
        await self._client.close()

    async def complete_structured(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        cache: LlmCache,
        role: ModelRole,
        task_category: str,
        system: str,
        user: str,
        response_model: type[T],
        calls_this_workflow: int,
        max_output_tokens: int | None = None,
    ) -> T:
        """Make one structured LLM call, or return a cached result for an
        identical (model, task_category, prompt) triple.

        Raises :class:`~opensource_scout.llm.router.ModelUnavailableError`,
        :class:`~opensource_scout.llm.budget.BudgetExceededError`,
        :class:`~opensource_scout.llm.errors.MalformedOutputError`, or
        :class:`~opensource_scout.llm.errors.LlmApiError`.
        """
        model = resolve_model(settings, role)
        budget.check_call_count(settings, calls_this_workflow)

        prompt = f"{system}\x00{user}"
        cache_key = compute_cache_key(model, task_category, prompt)

        cached = cache.get(cache_key)
        if cached is not None:
            self._record_call(
                session_factory,
                task_category=task_category,
                model=model,
                cache_key=cache_key,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=0,
                cache_status="HIT",
            )
            return _validate_or_raise(response_model, cached)

        estimated_input_tokens = _estimate_tokens(prompt)
        if estimated_input_tokens > settings.max_input_tokens_per_call:
            raise LlmApiError(
                f"prompt is ~{estimated_input_tokens} tokens, "
                f"over the {settings.max_input_tokens_per_call} limit for a single call"
            )

        output_cap = max_output_tokens or settings.max_output_tokens_per_call
        estimated_cost = estimate_cost_usd(model, estimated_input_tokens, output_cap)
        with session_factory() as session:
            budget.check_budget(session, settings, estimated_additional_cost_usd=estimated_cost)

        started = time.monotonic()
        parsed = await self._call_with_one_retry(
            model=model,
            system=system,
            user=user,
            response_model=response_model,
            output_cap=output_cap,
        )
        latency_ms = int((time.monotonic() - started) * 1000)

        input_tokens = parsed.usage_input_tokens
        output_tokens = parsed.usage_output_tokens
        cost_usd = estimate_cost_usd(model, input_tokens, output_tokens)

        self._record_call(
            session_factory,
            task_category=task_category,
            model=model,
            cache_key=cache_key,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            cache_status="MISS",
        )
        cache.set(cache_key, model=model, response=parsed.output.model_dump(mode="json"))
        return parsed.output

    async def _call_with_one_retry(
        self,
        *,
        model: str,
        system: str,
        user: str,
        response_model: type[T],
        output_cap: int,
    ) -> _ParsedResult[T]:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = await self._client.responses.parse(
                    model=model,
                    instructions=system,
                    input=user,
                    text_format=response_model,
                    max_output_tokens=output_cap,
                )
            except OpenAIError as exc:
                raise LlmApiError(f"OpenAI API error calling {model}: {exc}") from exc
            except ValidationError as exc:
                # The SDK raises directly (rather than leaving output_parsed
                # None) when the model's text doesn't parse into our schema.
                last_error = MalformedOutputError(
                    f"attempt {attempt + 1}: model {model} returned output that "
                    f"doesn't match {response_model.__name__}: {exc}"
                )
                logger.warning(str(last_error))
                continue

            output = response.output_parsed
            if output is not None:
                usage = response.usage
                return _ParsedResult(
                    output=output,
                    usage_input_tokens=usage.input_tokens if usage else 0,
                    usage_output_tokens=usage.output_tokens if usage else 0,
                )
            last_error = MalformedOutputError(
                f"attempt {attempt + 1}: model {model} did not return a parseable "
                f"{response_model.__name__}"
            )
            logger.warning(str(last_error))

        raise last_error or MalformedOutputError(f"model {model} returned no parseable output")

    def _record_call(
        self,
        session_factory: sessionmaker[Session],
        *,
        task_category: str,
        model: str,
        cache_key: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: int,
        cache_status: str,
    ) -> None:
        response_hash = (
            hashlib.sha256(cache_key.encode()).hexdigest() if cache_status == "HIT" else None
        )
        with session_factory() as session:
            session.add(
                LlmCallRow(
                    task_category=task_category,
                    model=model,
                    prompt_hash=cache_key,
                    response_hash=response_hash,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    estimated_cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    cache_status=cache_status,
                )
            )
            session.commit()


@dataclass
class _ParsedResult[T: BaseModel]:
    output: T
    usage_input_tokens: int
    usage_output_tokens: int


def _validate_or_raise[T: BaseModel](response_model: type[T], data: dict) -> T:
    try:
        return response_model.model_validate(data)
    except ValidationError as exc:
        raise MalformedOutputError(f"cached response no longer matches schema: {exc}") from exc


__all__ = ["OpenAiClient"]
