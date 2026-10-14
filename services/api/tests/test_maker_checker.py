from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.maker_checker import assert_maker_checker
from treasurypilot_api.main import create_app

MAKER = uuid.uuid4()
EDITOR = uuid.uuid4()
CHECKER = uuid.uuid4()


@dataclass(frozen=True)
class Request:
    created_by: uuid.UUID | None
    last_edited_by: uuid.UUID | None


@dataclass(frozen=True)
class Organization:
    solo_mode: bool


REQUEST = Request(created_by=MAKER, last_edited_by=EDITOR)


@pytest.mark.parametrize("approver", [MAKER, EDITOR])
def test_creator_and_last_editor_are_rejected_when_solo_mode_is_off(
    approver: uuid.UUID,
) -> None:
    with pytest.raises(AuthFailure) as failure:
        assert_maker_checker(REQUEST, user_id=approver, organization=Organization(False))

    assert (failure.value.status, failure.value.code) == (409, "MAKER_CHECKER")


@pytest.mark.parametrize("approver", [MAKER, EDITOR])
def test_solo_mode_allows_self_approval_and_marks_audit(
    approver: uuid.UUID,
) -> None:
    decision = assert_maker_checker(REQUEST, user_id=approver, organization=Organization(True))

    assert decision.solo_mode is True
    assert decision.audit_data() == {"solo_mode": True}


@pytest.mark.parametrize("solo_mode", [False, True])
def test_independent_approver_is_never_marked_as_solo(solo_mode: bool) -> None:
    decision = assert_maker_checker(REQUEST, user_id=CHECKER, organization=Organization(solo_mode))

    assert decision.solo_mode is False
    assert decision.audit_data() == {"solo_mode": False}


def test_request_without_recorded_maker_fails_closed() -> None:
    orphan = Request(created_by=None, last_edited_by=None)

    with pytest.raises(AuthFailure) as failure:
        assert_maker_checker(orphan, user_id=CHECKER, organization=Organization(False))
    assert (failure.value.status, failure.value.code) == (409, "MAKER_CHECKER")

    decision = assert_maker_checker(orphan, user_id=CHECKER, organization=Organization(True))
    assert decision.solo_mode is True


def test_maker_checker_failure_maps_to_a_409_problem_response() -> None:
    app = create_app(settings=Settings(environment="local"))

    @app.post("/_approve")
    async def approve() -> None:
        assert_maker_checker(REQUEST, user_id=MAKER, organization=Organization(False))

    response = TestClient(app, raise_server_exceptions=False).post("/_approve")

    assert response.status_code == 409
    assert response.json()["code"] == "MAKER_CHECKER"
