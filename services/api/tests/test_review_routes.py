from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from treasurypilot_api.identity.access import MemberContext, require_member
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.state_machine import TransitionForbidden
from treasurypilot_api.review.models import ReviewAction, ReviewStatus
from treasurypilot_api.review.routes import (
    ReviewActionNotAllowed,
    ReviewForbidden,
    ReviewNotFound,
    ReviewTransitionsUnavailable,
    StaleReviewItem,
    router,
)

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000111")
USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000333")
ITEM_ID = uuid.UUID("00000000-0000-4000-8000-000000000444")


class _ActionRepository:
    failure: Exception = ReviewForbidden()
    listed: dict[str, object] = {}

    async def list_items(self, **kwargs: object) -> tuple[()]:
        self.listed = kwargs
        return ()

    async def get_item(self, **_: object) -> None:
        return None

    async def act(self, **_: object) -> object:
        raise self.failure


def _client(repository: _ActionRepository, *, roles: frozenset[str]) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.review_repository = repository
    app.add_exception_handler(AuthFailure, problem_response)
    app.dependency_overrides[require_member] = lambda: MemberContext(ORG_ID, USER_ID, roles)
    return TestClient(app)


def test_action_endpoint_returns_not_routed_role_for_wrong_role() -> None:
    repository = _ActionRepository()
    repository.failure = ReviewForbidden()
    client = _client(repository, roles=frozenset({"Operator"}))

    response = client.post(
        f"/v1/orgs/{ORG_ID}/review-items/{ITEM_ID}/actions",
        json={"action": ReviewAction.CANCEL.value, "version": 1},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "NOT_ROUTED_ROLE"


def test_action_endpoint_returns_stale_item_conflict() -> None:
    repository = _ActionRepository()
    repository.failure = StaleReviewItem()
    client = _client(repository, roles=frozenset({"Owner"}))

    response = client.post(
        f"/v1/orgs/{ORG_ID}/review-items/{ITEM_ID}/actions",
        json={"action": ReviewAction.CANCEL.value, "version": 1},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "STALE_ITEM"


def test_action_endpoint_rejects_actions_outside_the_route() -> None:
    repository = _ActionRepository()
    repository.failure = ReviewActionNotAllowed()
    client = _client(repository, roles=frozenset({"Owner"}))

    response = client.post(
        f"/v1/orgs/{ORG_ID}/review-items/{ITEM_ID}/actions",
        json={"action": ReviewAction.RETRY.value, "version": 1},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "ACTION_NOT_ALLOWED"


def test_action_endpoint_hides_missing_items() -> None:
    repository = _ActionRepository()
    repository.failure = ReviewNotFound()
    client = _client(repository, roles=frozenset({"Owner"}))

    response = client.post(
        f"/v1/orgs/{ORG_ID}/review-items/{ITEM_ID}/actions",
        json={"action": ReviewAction.CANCEL.value, "version": 1},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "REVIEW_NOT_FOUND"


def _post(repository: _ActionRepository, action: ReviewAction) -> object:
    client = _client(repository, roles=frozenset({"Operator"}))
    return client.post(
        f"/v1/orgs/{ORG_ID}/review-items/{ITEM_ID}/actions",
        json={"action": action.value, "version": 1},
    )


def test_a_request_that_refuses_the_move_is_reported_with_its_code() -> None:
    repository = _ActionRepository()
    repository.failure = TransitionForbidden("The actor does not have permission.")
    response = _post(repository, ReviewAction.CANCEL)
    assert response.status_code == 403  # type: ignore[attr-defined]
    assert response.json()["code"] == "TRANSITION_FORBIDDEN"  # type: ignore[attr-defined]


def test_actions_that_move_the_request_fail_closed_without_a_state_machine() -> None:
    repository = _ActionRepository()
    repository.failure = ReviewTransitionsUnavailable()
    response = _post(repository, ReviewAction.RETRY)
    assert response.status_code == 503  # type: ignore[attr-defined]


def test_list_defaults_to_open_items_with_a_limit() -> None:
    repository = _ActionRepository()
    client = _client(repository, roles=frozenset({"Operator"}))
    assert client.get(f"/v1/orgs/{ORG_ID}/review-items").status_code == 200
    assert repository.listed["status"] == ReviewStatus.OPEN
    assert repository.listed["limit"] == 100
    client.get(f"/v1/orgs/{ORG_ID}/review-items?includeClosed=true&limit=5")
    assert (repository.listed["status"], repository.listed["limit"]) == (None, 5)
