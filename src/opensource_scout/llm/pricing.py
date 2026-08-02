"""Approximate per-model pricing, used only to estimate cost before/after a
call — never to decide whether a call is technically possible. Prices are in
USD per 1,000 tokens and will drift out of date; treat them as directional,
not authoritative. Unknown models fall back to a conservative default so an
unrecognized model name doesn't silently report zero cost.
"""

from __future__ import annotations

# (input $/1K tokens, output $/1K tokens)
_PRICING_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.0025, 0.010),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4.1": (0.002, 0.008),
    "gpt-4.1-mini": (0.0004, 0.0016),
    "gpt-4.1-nano": (0.0001, 0.0004),
    "o1": (0.015, 0.060),
    "o3-mini": (0.0011, 0.0044),
}

_DEFAULT_PRICING = (0.005, 0.015)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    input_rate, output_rate = _PRICING_PER_1K.get(model, _DEFAULT_PRICING)
    return (input_tokens / 1000) * input_rate + (output_tokens / 1000) * output_rate
