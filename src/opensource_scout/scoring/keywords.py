"""Keyword signals shared by project and issue scoring."""

from __future__ import annotations

# Keywords that indicate hardware requirements incompatible with a CPU-only
# MacBook Air, per the developer's stated constraints.
GPU_KEYWORDS: tuple[str, ...] = (
    "cuda",
    "nvidia",
    "gpu-only",
    "multi-gpu",
    "tensorrt",
    "distributed training",
    "large-scale training",
)


def keyword_overlap(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [k for k in keywords if k.lower() in text]
