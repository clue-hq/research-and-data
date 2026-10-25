"""Onboarding pre-flight: the providers it needs, checked before a run spends (spec 2026-10-25 §3.3).

Offline: OpenRouter and the design API are answered by a scripted transport; the Exa probe is a
fake (its real body is a one-result search through the provider caller).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import httpx
from pydantic import SecretStr

from clue_api.workspace_ops.preflight import (
    PreflightReport,
    ProbeResult,
    check_providers,
)
from clue_config import Secrets, Settings

_KEY_OK = {"data": {"limit": None, "limit_remaining": None, "effective_budget": None}}


def _transport(
    routes: dict[str, tuple[int, Any]], seen: list[httpx.Request]
) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        for suffix, (status, body) in routes.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})

    return httpx.MockTransport(handle)


def _exa(outcome: str = "ok") -> Any:
    async def probe(workspace_id: str) -> ProbeResult:
        return ProbeResult(
            provider="exa", outcome=outcome, required=True, detail=outcome, credit_usd=None
        )

    return probe


def _check(
    routes: dict[str, tuple[int, Any]],
    *,
    exa: str = "ok",
    openrouter_key: str | None = "or-key",
    env: dict[str, str] | None = None,
) -> tuple[PreflightReport, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    secrets = Secrets(
        openrouter_api_key=SecretStr(openrouter_key) if openrouter_key else None,
        exa_api_key=SecretStr("exa-key"),
    )
    settings = Settings(design_api_base_url="http://design.internal")

    async def run() -> PreflightReport:
        async with httpx.AsyncClient(transport=_transport(routes, seen)) as http:
            return await check_providers(
                secrets=secrets,
                settings=settings,
                workspace_id="ws-pf",
                http=http,
                exa_probe=_exa(exa),
                env=env or {},
            )

    return asyncio.run(run()), seen


def _by(report: PreflightReport) -> dict[str, ProbeResult]:
    return {result.provider: result for result in report.results}


_HEALTHY = {"/api/v1/key": (200, _KEY_OK), "/api/v1/credits": (403, {}), "/healthz": (200, {})}


def test_a_healthy_deployment_has_nothing_blocking() -> None:
    report, _ = _check(_HEALTHY)
    assert report.blocking == ()
    assert _by(report)["openrouter_platform"].outcome == "ok"
    assert _by(report)["design_api"].outcome == "ok"


def test_disabled_openrouter_key_blocks() -> None:
    report, _ = _check({**_HEALTHY, "/api/v1/key": (401, {"error": {"message": "User not found"}})})
    result = _by(report)["openrouter_platform"]
    assert result.outcome == "key_invalid"
    assert result in report.blocking


def test_openrouter_zero_budget_is_no_credit_and_below_floor_is_low_credit() -> None:
    def key(remaining: float) -> dict[str, Any]:
        return {"data": {"limit_remaining": None, "effective_budget": {"remaining_usd": remaining}}}

    empty, _ = _check({**_HEALTHY, "/api/v1/key": (200, key(0))})
    assert _by(empty)["openrouter_platform"].outcome == "no_credit"
    assert _by(empty)["openrouter_platform"] in empty.blocking
    low, _ = _check({**_HEALTHY, "/api/v1/key": (200, key(2.5))})
    assert _by(low)["openrouter_platform"].outcome == "low_credit"
    assert _by(low)["openrouter_platform"].credit_usd == Decimal("2.5")
    assert low.blocking == ()


def test_credits_endpoint_balance_is_used_when_readable() -> None:
    report, _ = _check(
        {**_HEALTHY, "/api/v1/credits": (200, {"data": {"total_credits": 10, "total_usage": 9.5}})}
    )
    result = _by(report)["openrouter_platform"]
    assert (result.outcome, result.credit_usd) == ("low_credit", Decimal("0.5"))


def test_missing_key_is_not_configured_and_sends_nothing() -> None:
    report, seen = _check(_HEALTHY, openrouter_key=None)
    assert _by(report)["openrouter_platform"].outcome == "not_configured"
    assert _by(report)["openrouter_platform"] in report.blocking
    assert not any("openrouter" in str(request.url) for request in seen)


def test_a_distinct_design_key_is_probed_on_its_own() -> None:
    report, seen = _check(_HEALTHY, env={"OPENROUTER_API_KEY": "design-key"})
    assert _by(report)["openrouter_design"].outcome == "ok"
    keys = {request.headers["authorization"] for request in seen if "/key" in str(request.url)}
    assert keys == {"Bearer or-key", "Bearer design-key"}


def test_exa_payment_required_blocks() -> None:
    report, _ = _check(_HEALTHY, exa="no_credit")
    assert _by(report)["exa"] in report.blocking


def test_unreachable_design_api_blocks() -> None:
    report, _ = _check({**_HEALTHY, "/healthz": (503, {})})
    assert _by(report)["design_api"].outcome == "unreachable"
    assert _by(report)["design_api"] in report.blocking


def test_ad_lane_keys_only_warn() -> None:
    report, _ = _check(_HEALTHY, env={"LUMEN_BRAND_AD_ASSETS": "1"})
    adyntel = _by(report)["adyntel"]
    assert (adyntel.outcome, adyntel.required) == ("not_configured", False)
    assert report.blocking == ()
