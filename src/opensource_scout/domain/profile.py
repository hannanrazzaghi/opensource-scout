"""The concrete developer profile OpenSourceScout evaluates projects and
issues against.

This is deliberately plain data, not something inferred by an LLM: career
relevance and hardware-compatibility scoring (see
:mod:`opensource_scout.scoring`) need a stable, reviewable ground truth to
compare candidates against.
"""

from __future__ import annotations

from opensource_scout.domain.models import Profile

HANNAN_PROFILE = Profile(
    name="Hannan Razzaghi",
    github_username="hannanrazzaghi",
    github_url="https://github.com/hannanrazzaghi",
    operating_system="macOS",
    hardware="MacBook Air",
    weekly_hours_min=3.0,
    weekly_hours_max=5.0,
    primary_objective="Build strong résumé credibility through meaningful merged contributions",
    skills=(
        "Python",
        "Rust",
        "Backend engineering",
        "LLM agents",
        "AI infrastructure",
        "Production AI systems",
        "Django",
        "PostgreSQL",
        "SQLite",
        "Tree-sitter",
        "BM25",
        "Graph algorithms",
        "Personalized PageRank",
        "Code indexing",
        "Static analysis",
        "Retrieval systems",
        "Performance optimization",
        "Concurrent services",
        "Testing and debugging",
        "System design",
    ),
    interests=(
        "Algorithms",
        "Mathematics",
        "Optimization",
        "Search and ranking",
        "Graph algorithms",
        "Retrieval",
        "Code intelligence",
        "AI coding tools",
        "LLM infrastructure",
        "AI agents",
        "Model evaluation",
        "Developer tools",
        "Databases",
        "Distributed systems",
        "Performance engineering",
        "Reliability",
        "Parsers and compilers",
        "Emerging ML-engineering and software-engineering concepts",
    ),
    hardware_constraints=(
        "Do not prioritize CUDA",
        "Do not prioritize NVIDIA-only projects",
        "Avoid large-model training",
        "Avoid multi-GPU development",
        "Avoid expensive cloud requirements",
        "Avoid extremely large local builds",
        "Prefer CPU-compatible targeted tests",
        "Prefer projects that work well on macOS and a MacBook Air",
    ),
)
