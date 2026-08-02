"""Safe, typed command execution.

Every command is a declared specification — executable, argument array,
working directory, timeout, network requirement, and risk classification —
never a raw shell string. `shell=True` is never used anywhere in this
module. A fixed blocklist rejects unscoped deletion, credential/SSH-key
reads, `sudo`, and other destructive or privilege-escalating patterns before
a process is ever spawned, regardless of what risk classification the
caller claims.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from opensource_scout.db.models import CommandRunRow
from opensource_scout.logging import get_logger, redact

logger = get_logger("execution.command")

_DEFAULT_TIMEOUT_SECONDS = 120.0
_OUTPUT_EXCERPT_LIMIT = 4000


class RiskClassification(StrEnum):
    READ_ONLY = "read_only"
    """git status, rg, safe file inspection, format/lint/type checks, tests."""

    LOCAL_WRITE = "local_write"
    """Writes inside the workspace only — no network, no external remotes."""

    EXTERNAL = "external"
    """Touches an external remote, credentials, or otherwise requires
    explicit human approval before it can run (see
    :mod:`opensource_scout.approvals`)."""


class CommandRejectedError(Exception):
    """Raised when a command is blocked outright, regardless of its claimed
    risk classification or any approval. These patterns are never allowed:
    the blocklist is not something approval can override."""


# Argument patterns that are always rejected, no matter the declared risk
# classification or approval state. Recursive-delete scoping (`rm -r`/`-rf`)
# is handled separately below, since a scoped deletion inside the working
# directory is legitimate.
_BLOCKED_ARG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\.ssh(/|$)"),
    re.compile(r"\.aws(/|$)"),
    re.compile(r"Library/Application Support/(Google/Chrome|Firefox)"),
    re.compile(r"^--privileged$"),
)
_BLOCKED_EXECUTABLES: frozenset[str] = frozenset({"sudo", "doas", "su"})
_DESTRUCTIVE_GIT_ARGS: frozenset[str] = frozenset(
    {"push --force", "push -f", "reset --hard", "clean -fd", "clean -xfd"}
)


@dataclass(frozen=True)
class CommandSpec:
    executable: str
    args: tuple[str, ...]
    working_directory: Path
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    network_required: bool = False
    expected_output: str = ""
    risk: RiskClassification = RiskClassification.READ_ONLY
    contribution_id: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool


def _validate_spec(spec: CommandSpec) -> None:
    if spec.executable in _BLOCKED_EXECUTABLES:
        raise CommandRejectedError(f"executable {spec.executable!r} is never allowed")

    joined = " ".join(spec.args)
    for pattern in _BLOCKED_ARG_PATTERNS:
        if any(pattern.search(a) for a in spec.args):
            raise CommandRejectedError(f"argument matched blocked pattern {pattern.pattern!r}")

    if spec.executable == "git":
        for destructive in _DESTRUCTIVE_GIT_ARGS:
            if destructive in joined:
                raise CommandRejectedError(f"destructive git operation blocked: {destructive!r}")

    is_recursive_delete = "-r" in spec.args or "-rf" in spec.args or "-fr" in spec.args
    if spec.executable == "rm" and is_recursive_delete:
        # Recursive deletion is only ever allowed when every path argument
        # is safely inside the command's own working directory.
        paths = [a for a in spec.args if not a.startswith("-")]
        for p in paths:
            resolved = (spec.working_directory / p).resolve()
            if not str(resolved).startswith(str(spec.working_directory.resolve())):
                raise CommandRejectedError(
                    f"recursive delete of {p!r} escapes the working directory"
                )

    if spec.risk == RiskClassification.EXTERNAL and spec.network_required:
        logger.info(
            "external, network-requiring command declared: %s %s "
            "— caller must hold a valid approval",
            spec.executable,
            joined,
        )


async def run_command(
    spec: CommandSpec, *, session_factory: sessionmaker[Session] | None = None
) -> CommandResult:
    """Run one command as an argument array (never a shell string), enforce
    the blocklist first, and record the outcome (with redacted output) if a
    session factory is provided."""
    _validate_spec(spec)

    started = time.monotonic()
    timed_out = False
    stdout_text = ""
    stderr_text = ""
    exit_code: int | None = None

    process = await asyncio.create_subprocess_exec(
        spec.executable,
        *spec.args,
        cwd=str(spec.working_directory),
        env=spec.env or None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=spec.timeout_seconds
        )
        exit_code = process.returncode
    except TimeoutError:
        timed_out = True
        process.kill()
        await process.wait()
        stdout_bytes, stderr_bytes = b"", b""

    duration = time.monotonic() - started
    stdout_text = redact(stdout_bytes.decode("utf-8", errors="replace"))[:_OUTPUT_EXCERPT_LIMIT]
    stderr_text = redact(stderr_bytes.decode("utf-8", errors="replace"))[:_OUTPUT_EXCERPT_LIMIT]

    result = CommandResult(
        exit_code=exit_code,
        stdout=stdout_text,
        stderr=stderr_text,
        duration_seconds=duration,
        timed_out=timed_out,
    )

    if session_factory is not None:
        with session_factory() as session:
            session.add(
                CommandRunRow(
                    contribution_id=spec.contribution_id,
                    command_json={"executable": spec.executable, "args": list(spec.args)},
                    working_directory=str(spec.working_directory),
                    duration_seconds=result.duration_seconds,
                    exit_code=result.exit_code,
                    stdout_excerpt=result.stdout,
                    stderr_excerpt=result.stderr,
                    timed_out=result.timed_out,
                    risk_classification=spec.risk.value,
                )
            )
            session.commit()

    return result
