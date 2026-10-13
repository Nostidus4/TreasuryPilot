from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from treasurypilot_api.identity.access import maker_checker_conflict


class ApprovalRequest(Protocol):
    # Read-only members, so models with non-optional or read-only ids also satisfy it.
    @property
    def created_by(self) -> uuid.UUID | None: ...

    @property
    def last_edited_by(self) -> uuid.UUID | None: ...


class SoloModeSetting(Protocol):
    """The organization (e.g. ``Organization`` or ``OrganizationRecord``) owning the request."""

    @property
    def solo_mode(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class MakerCheckerDecision:
    """Approval metadata that must be stored on the approval and audit event."""

    # True only when solo mode actually allowed a self-approval (BR-005).
    solo_mode: bool

    def audit_data(self) -> dict[str, bool]:
        return {"solo_mode": self.solo_mode}


def assert_maker_checker(
    request: ApprovalRequest,
    *,
    user_id: uuid.UUID,
    organization: SoloModeSetting,
) -> MakerCheckerDecision:
    """Reject self-approval (409 ``MAKER_CHECKER``) unless the org has Owner-enabled solo mode.

    The solo-mode flag is read from the organization itself, never passed by the caller.
    """

    is_maker = user_id in {request.created_by, request.last_edited_by}
    if is_maker and not organization.solo_mode:
        raise maker_checker_conflict()
    return MakerCheckerDecision(solo_mode=is_maker)
