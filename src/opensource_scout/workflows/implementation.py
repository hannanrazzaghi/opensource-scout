"""Implementation planning and validation.

Planning calls the reasoning-role LLM for a structured
:class:`~opensource_scout.domain.llm_models.ImplementationPlan`, built from a
deterministic context bundle — never a full repository dump (see
:mod:`opensource_scout.llm.context`). Validation runs the repository's own
declared commands (test/lint/format/typecheck, from
:mod:`opensource_scout.repository.rules`) through the safe command runner
and reports an honest status per command; nothing is ever described as
"passed" without a zero exit code to show for it.

This module does not write code to disk. Per the project's safety model, a
generated patch is surfaced for human review (see the ``claude_bridge`` and
``pr`` workflows) rather than applied automatically.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from opensource_scout.config import Settings
from opensource_scout.domain.context import ContextBundle
from opensource_scout.domain.enums import ValidationStatus
from opensource_scout.domain.llm_models import ImplementationPlan
from opensource_scout.domain.models import ValidationResult
from opensource_scout.execution.command import CommandSpec, RiskClassification, run_command
from opensource_scout.llm.cache import LlmCache
from opensource_scout.llm.client import OpenAiClient
from opensource_scout.llm.router import ModelRole

_PLANNING_SYSTEM_PROMPT = """\
You are a senior software engineer proposing a minimal, focused fix for an \
open-source issue. Ground every claim in the provided repository context. \
Prefer the smallest change that correctly addresses the problem; do not \
propose unrelated refactoring or cleanup. Always propose at least one \
regression test.\
"""

_VALIDATION_TIMEOUT_SECONDS = 300.0


def _build_planning_prompt(problem: str, context: ContextBundle) -> str:
    parts = [f"Problem:\n{problem}\n"]
    if context.relevant_tests:
        parts.append(f"Relevant existing tests: {', '.join(context.relevant_tests)}\n")
    parts.append("Repository context (deterministically selected, not exhaustive):\n")
    for f in context.selected_files:
        parts.append(f"--- {f.path} ---\n{f.content}\n")
    if context.excluded_files:
        parts.append(
            f"({len(context.excluded_files)} other files were considered but not "
            "included due to low relevance or the token budget.)"
        )
    return "\n".join(parts)


async def plan_implementation(
    *,
    settings: Settings,
    session_factory: sessionmaker[Session],
    cache: LlmCache,
    llm_client: OpenAiClient,
    problem: str,
    context: ContextBundle,
    calls_this_workflow: int,
) -> ImplementationPlan:
    """Produce a structured implementation plan via the reasoning-role LLM.
    Raises the same errors as
    :meth:`~opensource_scout.llm.client.OpenAiClient.complete_structured`."""
    return await llm_client.complete_structured(
        settings=settings,
        session_factory=session_factory,
        cache=cache,
        role=ModelRole.REASONING,
        task_category="implementation_planning",
        system=_PLANNING_SYSTEM_PROMPT,
        user=_build_planning_prompt(problem, context),
        response_model=ImplementationPlan,
        calls_this_workflow=calls_this_workflow,
    )


async def validate_contribution(
    workspace_path: Path,
    commands: dict[str, tuple[str, ...]],
    *,
    contribution_id: str,
    session_factory: sessionmaker[Session] | None = None,
) -> list[ValidationResult]:
    """Run each named command (e.g. ``{"test": ("pytest", "-q"), "lint":
    ("ruff", "check", ".")}``) against the workspace and report an honest
    :class:`~opensource_scout.domain.models.ValidationResult` per command.

    ``same_failure_on_base_commit`` is intentionally left unset: this
    project never applies generated patches automatically (see module
    docstring), so there is no modified-vs-base comparison to make here —
    validation always runs against the workspace's current, human-reviewed
    state.
    """
    results: list[ValidationResult] = []
    for name, args in commands.items():
        command_str = " ".join(args)
        try:
            outcome = await run_command(
                CommandSpec(
                    executable=args[0],
                    args=tuple(args[1:]),
                    working_directory=workspace_path,
                    timeout_seconds=_VALIDATION_TIMEOUT_SECONDS,
                    risk=RiskClassification.READ_ONLY,
                    contribution_id=contribution_id,
                ),
                session_factory=session_factory,
            )
        except FileNotFoundError:
            results.append(
                ValidationResult(
                    command=f"{name}: {command_str}",
                    status=ValidationStatus.UNAVAILABLE,
                    output_excerpt=f"executable {args[0]!r} not found in this environment",
                )
            )
            continue

        if outcome.timed_out:
            status = ValidationStatus.TIMED_OUT
        elif outcome.exit_code == 0:
            status = ValidationStatus.PASSED
        else:
            status = ValidationStatus.FAILED

        excerpt = (outcome.stdout + "\n" + outcome.stderr).strip()[-1000:]
        results.append(
            ValidationResult(
                command=f"{name}: {command_str}",
                status=status,
                exit_code=outcome.exit_code,
                duration_seconds=outcome.duration_seconds,
                output_excerpt=excerpt,
            )
        )

    return results
