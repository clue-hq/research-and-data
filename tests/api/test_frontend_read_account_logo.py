"""``GET /frontend/v1/accounts/{id}/logo`` streams the account's mark; anything else is a 404."""

from __future__ import annotations

import asyncio

import pytest

from clue_api.frontend_read import account_logo
from clue_api.frontend_read.account_logo import fetch_image
from clue_api.frontend_read.app import FRONTEND_READ_PREFIX

from .test_frontend_read_accounts_list import (
    _WS,
    _app,
    _build_v1,
    _client,
    _neutral_claim,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

MARK = "https://media.licdn.com/dms/image/v2/X/company-logo_200_200/0?e=2147483647"
PNG = b"\\x89PNG\\r\\n\\x1a\\n" + b"0" * 32


def test_the_route_streams_the_mark_with_its_content_type_and_404s_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched: list[str] = []

    async def scripted(url: str) -> tuple[bytes, str] | None:
        fetched.append(url)
        return (PNG, "image/png") if url == MARK else None

    monkeypatch.setattr(account_logo, "fetch_image", scripted)

    async def scenario() -> None:
        async with rollback_conn() as conn:
            _fixture, zafran = await _build_v1(conn)
            await _neutral_claim(conn, account_id=zafran, field_key="core.logo_url", value=MARK)
            async with _client(_app(conn)) as client:
                headers = {"X-Workspace-Id": _WS}
                ok = await client.get(
                    f"{FRONTEND_READ_PREFIX}/accounts/{zafran}/logo", headers=headers
                )
                # An account with no mark, and an id that is not an account at all.
                rows = (
                    await client.get(f"{FRONTEND_READ_PREFIX}/accounts", headers=headers)
                ).json()["data"]
                seedling = next(r["id"] for r in rows if r["name"] == "Seedling")
                none = await client.get(
                    f"{FRONTEND_READ_PREFIX}/accounts/{seedling}/logo", headers=headers
                )
                junk = await client.get(
                    f"{FRONTEND_READ_PREFIX}/accounts/not-a-uuid/logo", headers=headers
                )
            assert ok.status_code == 200
            assert ok.headers["content-type"].startswith("image/png")
            assert ok.headers["cache-control"] == "private, max-age=86400"
            assert ok.content == PNG
            assert fetched == [MARK]
            assert none.status_code == 404 and junk.status_code == 404

    run_async(scenario())


def test_fetch_image_refuses_non_https_without_a_request() -> None:
    assert asyncio.run(fetch_image("http://insecure.example/logo.png")) is None
    assert asyncio.run(fetch_image("javascript:alert(1)")) is None
