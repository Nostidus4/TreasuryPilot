from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.maker_checker import assert_maker_checker
from treasurypilot_api.main import create_app

MAKER, EDITOR, CHECKER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


@dataclass(frozen=True)
class Request:  # read-only, non-optional ids still satisfy ApprovalRequest
    created_by: uuid.UUID
    last_edited_by: uuid.UUID


@dataclass(frozen=True)
class Org:
    solo_mode: bool


REQUEST = Request(created_by=MAKER, last_edited_by=EDITOR)


@pytest.mark.parametrize("approver", [MAKER, EDITOR])
def test_creator_and_last_editor_are_rejected(approver: uuid.UUID) -> None:
    with pytest.raises(AuthFailure) as failure:
        assert_maker_checker(REQUEST, user_id=approver, organization=Org(solo_mode=False))
    assert (failure.value.status, failure.value.code) == (409, "MAKER_CHECKER")


@pytest.mark.parametrize("solo", [False, True])
def test_independent_approver_is_never_flagged_as_solo(solo: bool) -> None:
    decision = assert_maker_checker(REQUEST, user_id=CHECKER, organization=Org(solo_mode=solo))
    assert decision.solo_mode is False
    assert decision.audit_data() == {"solo_mode": False}


@pytest.mark.parametrize("approver", [MAKER, EDITOR])
def test_solo_mode_allows_and_flags_self_approval(approver: uuid.UUID) -> None:
    decision = assert_maker_checker(REQUEST, user_id=approver, organization=Org(solo_mode=True))
    assert decision.solo_mode is True


def test_violation_is_a_409_problem_not_a_500() -> None:
    app = create_app(settings=Settings(environment="local"))

    @app.post("/_approve")
    async def approve() -> None:
        assert_maker_checker(REQUEST, user_id=MAKER, organization=Org(solo_mode=False))

    response = TestClient(app, raise_server_exceptions=False).post("/_approve")
    assert response.status_code == 409
    assert response.json()["code"] == "MAKER_CHECKER"
