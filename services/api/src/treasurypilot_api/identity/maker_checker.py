"""Maker-checker decisions shared by payment approval handlers (BR-005)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from treasurypilot_api.identity.rbac import maker_checker_conflict


class ApprovalRequest(Protocol):
    @property
    def created_by(self) -> uuid.UUID | None: ...

    @property
    def last_edited_by(self) -> uuid.UUID | None: ...


class SoloModeSetting(Protocol):
    """Persisted organization settings; callers must not pass request input here."""

    @property
    def solo_mode(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class MakerCheckerDecision:
    """Whether solo mode allowed this maker to approve their own request."""

    solo_mode: bool

    def audit_data(self) -> dict[str, bool]:
        return {"solo_mode": self.solo_mode}


def assert_maker_checker(
    request: ApprovalRequest,
    *,
    user_id: uuid.UUID,
    organization: SoloModeSetting,
) -> MakerCheckerDecision:
    """Reject self-approval unless Owner-enabled solo mode is persisted for the org.

    The decision is true only when solo mode actually allowed a creator or last
    editor to approve. Independent approvers are never labeled as solo approvals.
    """

    is_maker = user_id in {request.created_by, request.last_edited_by}
    if is_maker and not organization.solo_mode:
        raise maker_checker_conflict()
    return MakerCheckerDecision(solo_mode=is_maker)
