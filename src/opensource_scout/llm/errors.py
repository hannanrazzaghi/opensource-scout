from __future__ import annotations


class LlmError(Exception):
    """Base class for LLM-layer errors."""


class MalformedOutputError(LlmError):
    """Raised when the model's output didn't parse into the requested
    structured shape, even after one retry."""


class LlmApiError(LlmError):
    """Wraps an underlying OpenAI SDK error so callers don't need to import
    or catch `openai.*` exception types directly."""
