import pytest

from opensource_scout.config import Settings
from opensource_scout.llm.router import ModelRole, ModelUnavailableError, resolve_model


def test_resolve_model_returns_configured_model_per_role() -> None:
    settings = Settings(
        OPENAI_MODEL_FAST="gpt-4o-mini",
        OPENAI_MODEL_REASONING="gpt-4o",
        OPENAI_MODEL_CODING="gpt-4o",
    )
    assert resolve_model(settings, ModelRole.FAST) == "gpt-4o-mini"
    assert resolve_model(settings, ModelRole.REASONING) == "gpt-4o"
    assert resolve_model(settings, ModelRole.CODING) == "gpt-4o"


def test_same_model_can_serve_multiple_roles() -> None:
    settings = Settings(
        OPENAI_MODEL_FAST="gpt-4o-mini",
        OPENAI_MODEL_REASONING="gpt-4o-mini",
        OPENAI_MODEL_CODING="gpt-4o-mini",
    )
    assert resolve_model(settings, ModelRole.FAST) == resolve_model(settings, ModelRole.REASONING)


def test_empty_model_raises_model_unavailable() -> None:
    settings = Settings(OPENAI_MODEL_FAST="")
    with pytest.raises(ModelUnavailableError):
        resolve_model(settings, ModelRole.FAST)


def test_whitespace_only_model_raises_model_unavailable() -> None:
    settings = Settings(OPENAI_MODEL_REASONING="   ")
    with pytest.raises(ModelUnavailableError):
        resolve_model(settings, ModelRole.REASONING)
