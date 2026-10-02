"""Provider protocol tests without network access or real email delivery."""

import json

import httpx
import pytest

from clue_auth.providers.clerk_api import ClerkApi, ClerkApiError
from tests.db.conftest import run_async


def test_invitation_delivery_and_verified_primary_address() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/invitations":
            return httpx.Response(200, json={"id": "inv_test"})
        if request.url.path.endswith("/revoke"):
            return httpx.Response(200, json={"revoked": True})
        return httpx.Response(
            200,
            json={
                "primary_email_address_id": "primary",
                "email_addresses": [
                    {
                        "id": "secondary",
                        "email_address": "wrong@example.com",
                        "verification": {"status": "verified"},
                    },
                    {
                        "id": "primary",
                        "email_address": " Alice@Example.com ",
                        "verification": {"status": "verified"},
                    },
                ],
            },
        )

    async def scenario() -> None:
        api = ClerkApi("test-only-secret", transport=httpx.MockTransport(handler))
        assert (
            await api.create_invitation(
                email="alice@example.com",
                redirect_url="http://localhost/invite/accept?token=test-only",
                invitation_id="wi_test",
            )
            == "inv_test"
        )
        await api.revoke_invitation("inv_test")
        assert await api.primary_email("user_test") == "alice@example.com"
        body = json.loads(requests[0].content)
        assert body["public_metadata"] == {"clue_invitation_id": "wi_test"}
        assert body["expires_in_days"] == 30
        assert "organization_id" not in body
        assert requests[1].url.path == "/v1/invitations/inv_test/revoke"

    run_async(scenario())


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (429, {}, "rate_limited"),
        (422, {"errors": [{"code": "form_identifier_exists"}]}, "existing_account"),
        (503, {"errors": None}, "unavailable"),
        (422, {"errors": [{"code": []}]}, "unavailable"),
        (200, [], "unavailable"),
    ],
)
def test_classified_provider_failures(status: int, body: object, code: str) -> None:
    async def scenario() -> None:
        api = ClerkApi(
            "test-only-secret",
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)),
        )
        with pytest.raises(ClerkApiError) as error:
            await api.create_invitation(
                email="alice@example.com", redirect_url="http://localhost", invitation_id="wi_test"
            )
        assert error.value.code == code
        assert "test-only-secret" not in str(error.value)

    run_async(scenario())


def test_verified_address_without_primary_id_is_not_accepted() -> None:
    async def scenario() -> None:
        api = ClerkApi(
            "test-only-secret",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "email_addresses": [
                            {
                                "email_address": "alice@example.com",
                                "verification": {"status": "verified"},
                            }
                        ]
                    },
                )
            ),
        )
        assert await api.primary_profile("user_test") is None

    run_async(scenario())


@pytest.mark.parametrize(
    "addresses",
    [
        None,
        [],
        [
            {
                "id": "primary",
                "email_address": "unverified@example.com",
                "verification": {"status": "unverified"},
            }
        ],
    ],
)
def test_unverified_or_missing_primary_address_is_not_accepted(addresses: object) -> None:
    async def scenario() -> None:
        api = ClerkApi(
            "test-only-secret",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"primary_email_address_id": "primary", "email_addresses": addresses}
                )
            ),
        )
        assert await api.primary_email("user_test") is None

    run_async(scenario())
