from __future__ import annotations

import json

import httpx
import pytest

from clue_api.cloudflare_custom_hostnames import CloudflareCustomHostnames, CloudflareError
from tests.db.conftest import run_async

ZONE = "zone123"
CREATED = {
    "success": True,
    "errors": [],
    "messages": [],
    "result": {
        "id": "ch_1",
        "hostname": "go.acme.com",
        "status": "pending",
        "ssl": {
            "status": "pending_validation",
            "method": "http",
            "type": "dv",
            "validation_errors": [],
        },
        "ownership_verification": {
            "type": "txt",
            "name": "_cf-custom-hostname.go.acme.com",
            "value": "tok-1",
        },
        "verification_errors": [],
    },
}


def _client(handler):  # type: ignore[no-untyped-def]
    return CloudflareCustomHostnames(
        zone_id=ZONE,
        api_token="t0k",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_create_sends_the_documented_body_and_parses_the_record() -> None:
    async def scenario() -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, json=CREATED)

        record = await _client(handler).create("go.acme.com")
        assert (
            seen[0].method == "POST"
            and seen[0].url.path == f"/client/v4/zones/{ZONE}/custom_hostnames"
        )
        assert seen[0].headers["authorization"] == "Bearer t0k"
        assert json.loads(seen[0].content) == {
            "hostname": "go.acme.com",
            "ssl": {"method": "http", "type": "dv"},
        }
        assert (
            record.id == "ch_1"
            and record.status == "pending"
            and record.ssl_status == "pending_validation"
        )
        assert (
            record.ownership_txt_name == "_cf-custom-hostname.go.acme.com"
            and record.ownership_txt_value == "tok-1"
        )

    run_async(scenario())


def test_get_parses_errors_and_404_is_none() -> None:
    async def scenario() -> None:
        body = json.loads(json.dumps(CREATED))
        body["result"]["status"] = "active"
        body["result"]["ssl"]["status"] = "active"
        body["result"]["ssl"]["validation_errors"] = [{"message": "CAA record prevents issuance"}]
        body["result"]["verification_errors"] = ["ownership verification pending"]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ch_1"):
                return httpx.Response(200, json=body)
            return httpx.Response(
                404,
                json={
                    "success": False,
                    "errors": [{"code": 1436, "message": "not found"}],
                    "result": None,
                },
            )

        client = _client(handler)
        record = await client.get("ch_1")
        assert record is not None and record.status == "active" and record.ssl_status == "active"
        assert record.ssl_validation_errors == ("CAA record prevents issuance",)
        assert record.verification_errors == ("ownership verification pending",)
        assert await client.get("ch_missing") is None

    run_async(scenario())


def test_delete_treats_404_as_deleted_and_5xx_retries_once() -> None:
    async def scenario() -> None:
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if request.method == "DELETE" and request.url.path.endswith("/gone"):
                return httpx.Response(
                    404, json={"success": False, "errors": [{"code": 1436, "message": "not found"}]}
                )
            if calls["n"] == 1:
                return httpx.Response(502, text="bad gateway")
            return httpx.Response(
                200, json={"success": True, "errors": [], "result": {"id": "ch_1"}}
            )

        client = _client(handler)
        await client.delete("gone")
        calls["n"] = 0
        await client.delete("ch_1")
        assert calls["n"] == 2  # one retry on 5xx

    run_async(scenario())


def test_4xx_is_a_non_retryable_cloudflare_error_with_the_message() -> None:
    async def scenario() -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409,
                json={
                    "success": False,
                    "errors": [{"code": 1406, "message": "Duplicate custom hostname found."}],
                    "result": None,
                },
            )

        with pytest.raises(CloudflareError) as caught:
            await _client(handler).create("go.acme.com")
        assert caught.value.status == 409 and not caught.value.retryable
        assert "Duplicate custom hostname" in caught.value.message

    run_async(scenario())


def test_persistent_5xx_is_retryable() -> None:
    async def scenario() -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="down")

        with pytest.raises(CloudflareError) as caught:
            await _client(handler).create("go.acme.com")
        assert caught.value.retryable and caught.value.status == 503

    run_async(scenario())


def test_every_cloudflare_answer_is_reported_including_retried_ones() -> None:
    """Design 2026-10-31: each attempt's answer reaches the spend layer, so a refusal opens a
    provider incident; the client's own two-attempt retry is unchanged."""

    async def scenario() -> list[int]:
        observed: list[int] = []

        async def observe(**call: object) -> None:
            observed.append(int(call["status"]))  # type: ignore[call-overload]

        answers = iter([httpx.Response(503, text="busy"), httpx.Response(201, json=CREATED)])
        client = CloudflareCustomHostnames(
            zone_id=ZONE,
            api_token="t0k",
            client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(answers))),
            observe=observe,
        )
        await client.create("go.acme.com")
        return observed

    assert run_async(scenario()) == [503, 201]
