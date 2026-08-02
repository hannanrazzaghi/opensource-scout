"""Structured logging with automatic secret redaction.

Every log record passes through :class:`RedactionFilter`, which scrubs
token-shaped substrings (GitHub PATs, OpenAI keys, generic ``Bearer`` headers)
before the record is formatted. This is a defense-in-depth measure: call
sites should never log raw secrets in the first place, but a filter that
degrades gracefully on both the direct-message and formatted-args path is
what actually keeps them out of shipped log files.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# Patterns for common secret shapes. Order matters only for readability;
# each pattern is applied independently.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub PAT / OAuth / user-to-server tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),  # GitHub fine-grained PAT
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),  # OpenAI-style secret key
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{10,}"),  # Bearer <token>
)

REDACTED = "***REDACTED***"


def redact(text: str) -> str:
    """Replace any recognizable secret-shaped substring in ``text``."""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(rf"\1{REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


class RedactionFilter(logging.Filter):
    """Scrubs secret-shaped values from a log record's message and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive against bad %-args
            message = str(record.msg)
        record.msg = redact(message)
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    """Renders a log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "context", None)
        if extra:
            payload["context"] = extra
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure the root ``opensource_scout`` logger.

    Idempotent: safe to call multiple times (e.g. once from the CLI entry
    point and again in tests) without duplicating handlers.
    """
    logger = logging.getLogger("opensource_scout")
    logger.setLevel(level.upper())
    logger.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.addFilter(RedactionFilter())
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    logger.addHandler(handler)
    logger.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"opensource_scout.{name}")
