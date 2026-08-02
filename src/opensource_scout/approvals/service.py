"""Approval issuance, granting, and consumption.

An approval only becomes a valid, usable
:class:`~opensource_scout.domain.models.Approval` at the moment a human runs
`oss approve <approval-id>` — requesting one (`oss pr prepare`, `oss github
push`) only records a *pending* request. This is deliberate: the row in the
``approvals`` table represents "a human authorized this," not "the system
wants authorization," so its mere existence can be trusted by
:mod:`opensource_scout.workflows.state_machine` without checking anything
else.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from opensource_scout.db.models import ApprovalRow, ContributionRow
from opensource_scout.domain.enums import ApprovalKind
from opensource_scout.domain.models import Approval

DEFAULT_APPROVAL_WINDOW = timedelta(hours=24)


class ApprovalError(Exception):
    """Raised when an approval can't be requested, granted, or consumed."""


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite doesn't reliably round-trip timezone-aware datetimes through
    SQLAlchemy — values come back naive even though the column is declared
    ``DateTime(timezone=True)``. Every timestamp this module writes is UTC,
    so a naive value read back is assumed to be UTC too."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _row_to_domain(row: ApprovalRow) -> Approval:
    granted_at = _as_utc(row.granted_at)
    expires_at = _as_utc(row.expires_at)
    assert granted_at is not None
    assert expires_at is not None
    return Approval(
        approval_id=row.approval_id,
        contribution_id=row.contribution_id,
        kind=ApprovalKind(row.kind),
        granted_at=granted_at,
        expires_at=expires_at,
        used_at=_as_utc(row.used_at),
        note=row.note,
    )


def request_approval(
    session: Session, contribution_id: str, kind: ApprovalKind, *, note: str | None = None
) -> str:
    """Record a pending approval request on the contribution and return its
    ID. Does not create an ``approvals`` row — that only happens once a
    human actually grants it (see :func:`grant_approval`)."""
    contribution = session.execute(
        select(ContributionRow).where(ContributionRow.contribution_id == contribution_id)
    ).scalar_one_or_none()
    if contribution is None:
        raise ApprovalError(f"no contribution {contribution_id!r}")

    approval_id = str(uuid.uuid4())
    extra = dict(contribution.extra_json or {})
    pending = list(extra.get("pending_approvals", []))
    pending.append(
        {
            "approval_id": approval_id,
            "kind": kind.value,
            "requested_at": datetime.now(UTC).isoformat(),
            "note": note,
        }
    )
    extra["pending_approvals"] = pending
    contribution.extra_json = extra
    return approval_id


def grant_approval(
    session: Session, approval_id: str, *, window: timedelta = DEFAULT_APPROVAL_WINDOW
) -> Approval:
    """The human-facing `oss approve` action: find the pending request
    matching ``approval_id`` across all contributions, create the real,
    time-boxed :class:`~opensource_scout.domain.models.Approval` row, and
    remove it from the pending list."""
    contributions = session.execute(select(ContributionRow)).scalars().all()
    for contribution in contributions:
        extra = dict(contribution.extra_json or {})
        pending = list(extra.get("pending_approvals", []))
        match = next((p for p in pending if p["approval_id"] == approval_id), None)
        if match is None:
            continue

        now = datetime.now(UTC)
        row = ApprovalRow(
            approval_id=approval_id,
            contribution_id=contribution.contribution_id,
            kind=match["kind"],
            granted_at=now,
            expires_at=now + window,
            note=match.get("note"),
        )
        session.add(row)

        extra["pending_approvals"] = [p for p in pending if p["approval_id"] != approval_id]
        contribution.extra_json = extra
        session.flush()
        return _row_to_domain(row)

    raise ApprovalError(f"no pending approval request {approval_id!r}")


def find_valid_approval(
    session: Session, contribution_id: str, kind: ApprovalKind, *, now: datetime | None = None
) -> Approval | None:
    """Return the contribution's approval of this kind if one exists and is
    currently valid (granted, unexpired, unused) — otherwise ``None``."""
    at = now or datetime.now(UTC)
    rows = (
        session.execute(
            select(ApprovalRow).where(
                ApprovalRow.contribution_id == contribution_id,
                ApprovalRow.kind == kind.value,
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        approval = _row_to_domain(row)
        if approval.is_valid(at=at):
            return approval
    return None


def consume_approval(session: Session, approval_id: str) -> None:
    """Mark an approval as used. Single-use: a subsequent call to
    :func:`find_valid_approval` for the same approval will no longer return
    it."""
    row = session.execute(
        select(ApprovalRow).where(ApprovalRow.approval_id == approval_id)
    ).scalar_one_or_none()
    if row is None:
        raise ApprovalError(f"no approval {approval_id!r}")
    row.used_at = datetime.now(UTC)
