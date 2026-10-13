from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


class ApprovalRequest(Protocol):
    created_by: uuid.UUID | None
    last_edited_by: uuid.UUID | None


class MakerCheckerFailure(Exception):
    """The approver created or most recently edited the request."""

    code = "MAKER_CHECKER"


@dataclass(frozen=True, slots=True)
class MakerCheckerDecision:
    """Approval metadata that must be stored on the approval and audit event."""

    solo_mode: bool

    def audit_data(self) -> dict[str, bool]:
        return {"solo_mode": self.solo_mode}


def assert_maker_checker(
    request: ApprovalRequest,
    *,
    user_id: uuid.UUID,
    solo_mode: bool,
) -> MakerCheckerDecision:
    """Reject self-approval unless the organization has Owner-enabled solo mode."""

    if not solo_mode and user_id in {request.created_by, request.last_edited_by}:
        raise MakerCheckerFailure
    return MakerCheckerDecision(solo_mode=solo_mode)
