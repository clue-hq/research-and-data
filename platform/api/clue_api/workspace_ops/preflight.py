"""Onboarding pre-flight: check the providers before a run spends (spec 2026-10-25 §3.3).

On 2026-10-23 an onboarding "finished" in 2 seconds with empty folders because Exa was out of
credit, and a second one lost its ICP and every asset description to a disabled OpenRouter key.
This check runs before a run row exists and refuses when a required provider is dead.

| provider              | probe                                                      | cost      |
|-----------------------|------------------------------------------------------------|-----------|
| OpenRouter (platform) | ``GET /api/v1/key`` (+ ``/api/v1/credits`` when readable)  | free      |
| OpenRouter (design)   | the same, only when it is a different key                  | free      |
| Exa                   | one 1-result keyword search, ledgered to the workspace     | ~½ cent   |
| design API            | ``GET /healthz``                                           | free      |
| Adyntel, PDL          | key present (ad lane on only); never called; never blocks  | free      |

``/api/v1/key`` proves the key works and gives its own cap and its org budget; the account
balance is ``/api/v1/credits``, which some keys may not read — then the balance is reported as not
readable and a valid key passes. Exa has no free balance check (its usage API needs an admin key
and reports usage, not balance), so the probe is the cheapest real call.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx

from clue_config import Secrets, Settings
from clue_db import ConnFactory

ProbeOutcome = Literal[
    "ok", "low_credit", "no_credit", "key_invalid", "unreachable", "not_configured"
]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PROBE_TIMEOUT_S = 5.0
_PASSING = ("ok", "low_credit")


@dataclass(frozen=True)
class ProbeResult:
    provider: str
    outcome: ProbeOutcome
    required: bool
    detail: str
    credit_usd: Decimal | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "outcome": self.outcome,
            "required": self.required,
            "detail": self.detail,
            "credit_usd": None if self.credit_usd is None else str(self.credit_usd),
        }


@dataclass(frozen=True)
class PreflightReport:
    results: tuple[ProbeResult, ...]

    @property
    def blocking(self) -> tuple[ProbeResult, ...]:
        return tuple(r for r in self.results if r.required and r.outcome not in _PASSING)

    def as_json(self) -> dict[str, Any]:
        return {
            "results": [result.as_json() for result in self.results],
            "blocking": bool(self.blocking),
        }


ExaProbe = Callable[[str], Awaitable[ProbeResult]]


async def check_providers(
    *,
    secrets: Secrets,
    settings: Settings,
    workspace_id: str,
    http: httpx.AsyncClient,
    exa_probe: ExaProbe,
    env: Mapping[str, str] | None = None,
) -> PreflightReport:
    env = os.environ if env is None else env
    platform_key = _secret(secrets.openrouter_api_key)
    # The design ingestion gateway's own setting falls back to the platform key when blank.
    design_key = (env.get("OPENROUTER_API_KEY") or "").strip() or platform_key
    floor = settings.preflight_openrouter_min_credit_usd

    async def design_openrouter() -> ProbeResult:
        if design_key and design_key == platform_key:
            platform = await platform_probe
            return ProbeResult(
                "openrouter_design",
                platform.outcome,
                True,
                "same key as the platform",
                platform.credit_usd,
            )
        return await _openrouter("openrouter_design", design_key, http, floor)

    platform_probe = asyncio.ensure_future(
        _openrouter("openrouter_platform", platform_key, http, floor)
    )
    results = await asyncio.gather(
        platform_probe,
        design_openrouter(),
        _exa(secrets, workspace_id, exa_probe),
        _design_api(settings.design_api_base_url, http),
    )
    return PreflightReport(results=(*results, *_ad_lane(env)))


def _secret(value: Any) -> str | None:
    text = value.get_secret_value().strip() if value is not None else ""
    return text or None


async def _openrouter(
    provider: str, key: str | None, http: httpx.AsyncClient, floor: Decimal
) -> ProbeResult:
    if not key:
        return ProbeResult(provider, "not_configured", True, "no OpenRouter key is configured")
    headers = {"Authorization": f"Bearer {key}"}
    try:
        response = await http.get(
            f"{OPENROUTER_BASE_URL}/key", headers=headers, timeout=PROBE_TIMEOUT_S
        )
    except httpx.HTTPError as error:
        return ProbeResult(provider, "unreachable", True, f"{type(error).__name__}: {error}")
    if response.status_code in (401, 403):
        return ProbeResult(provider, "key_invalid", True, _message(response))
    if response.status_code == 402:
        return ProbeResult(provider, "no_credit", True, _message(response))
    if response.status_code != 200:
        return ProbeResult(provider, "unreachable", True, f"HTTP {response.status_code}")
    data = _data(response)
    if data is None:
        return ProbeResult(provider, "unreachable", True, "HTTP 200 with an unreadable body")
    figures = [
        _decimal(data.get("limit_remaining")),
        _decimal((data.get("effective_budget") or {}).get("remaining_usd")),
        await _balance(http, headers),
    ]
    readable = [figure for figure in figures if figure is not None]
    if not readable:
        return ProbeResult(provider, "ok", True, "key valid; balance not readable with this key")
    credit = min(readable)
    if credit <= 0:
        return ProbeResult(provider, "no_credit", True, f"${credit} left", credit)
    if credit < floor:
        return ProbeResult(provider, "low_credit", True, f"${credit} left (floor ${floor})", credit)
    return ProbeResult(provider, "ok", True, f"${credit} left", credit)


async def _balance(http: httpx.AsyncClient, headers: dict[str, str]) -> Decimal | None:
    try:
        response = await http.get(
            f"{OPENROUTER_BASE_URL}/credits", headers=headers, timeout=PROBE_TIMEOUT_S
        )
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    data = _data(response) or {}
    total, used = _decimal(data.get("total_credits")), _decimal(data.get("total_usage"))
    return None if total is None or used is None else total - used


async def _exa(secrets: Secrets, workspace_id: str, probe: ExaProbe) -> ProbeResult:
    if not _secret(secrets.exa_api_key):
        return ProbeResult("exa", "not_configured", True, "CLUE_EXA_API_KEY is not set")
    return await probe(workspace_id)


async def _design_api(base_url: str | None, http: httpx.AsyncClient) -> ProbeResult:
    if not base_url:
        return ProbeResult(
            "design_api", "not_configured", True, "CLUE_DESIGN_API_BASE_URL is unset"
        )
    try:
        response = await http.get(f"{base_url.rstrip('/')}/healthz", timeout=PROBE_TIMEOUT_S)
    except httpx.HTTPError as error:
        return ProbeResult("design_api", "unreachable", True, f"{type(error).__name__}: {error}")
    if response.status_code != 200:
        return ProbeResult("design_api", "unreachable", True, f"HTTP {response.status_code}")
    return ProbeResult("design_api", "ok", True, "reachable")


def _ad_lane(env: Mapping[str, str]) -> tuple[ProbeResult, ...]:
    if (env.get("LUMEN_BRAND_AD_ASSETS") or "").strip().lower() not in ("1", "true", "yes", "on"):
        return ()
    return tuple(
        ProbeResult(
            provider,
            "ok" if (env.get(key) or "").strip() else "not_configured",
            False,
            f"{key} {'set' if (env.get(key) or '').strip() else 'is not set'}",
        )
        for provider, key in (("adyntel", "ADYNTEL_API_KEY"), ("pdl", "PDL_API_KEY"))
    )


def _data(response: httpx.Response) -> dict[str, Any] | None:
    """The ``data`` object of an OpenRouter answer, or ``None`` when the body is not one."""
    try:
        body = response.json()
    except ValueError:
        return None
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else ({} if isinstance(body, dict) else None)


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return f"HTTP {response.status_code}: {message}" if message else f"HTTP {response.status_code}"


def build_exa_probe(
    secrets: Secrets, conn_factory: ConnFactory, *, caller_factory: Any = None
) -> ExaProbe:
    """The production Exa probe: one 1-result keyword search, ledgered to the workspace.

    ``caller_factory(raw=, ledger=)`` defaults to the onboarding lane's own provider caller; a
    test passes one over the lane's scripted transport.
    """
    from pydantic import SecretStr

    from clue_api.arv2.exa_client import ExaClient
    from clue_api.arv2.onboarding_driver import build_onboarding_provider_caller
    from clue_api.arv2.provider_ledger import (
        BufferedLedger,
        BufferedRawSink,
        drain_provider_calls,
    )
    from clue_spend import LedgerStamp, ProviderHalted

    async def probe(workspace_id: str) -> ProbeResult:
        key = SecretStr(_secret(secrets.exa_api_key) or "")
        raw, ledger = BufferedRawSink(), BufferedLedger()
        make_caller = caller_factory or build_onboarding_provider_caller
        client = ExaClient(make_caller(raw=raw, ledger=ledger), key)
        try:
            answer = await asyncio.to_thread(
                client.search,
                "example",
                type="keyword",
                num_results=1,
                label="onboarding-preflight",
                timeout_s=PROBE_TIMEOUT_S * 2,
            )
            # The client RETURNS a non-2xx answer (``status``) instead of raising — a bad key is a
            # returned 401 (found by the live proof, 2026-10-26). Only a 2xx is a working key.
            status = int(getattr(answer, "status", 200) or 200)
            if 200 <= status < 300:
                result = ProbeResult("exa", "ok", True, "a one-result search succeeded")
            elif status in (401, 403):
                result = ProbeResult(
                    "exa", "key_invalid", True, f"Exa refused the key (HTTP {status})"
                )
            elif status == 402:
                result = ProbeResult("exa", "no_credit", True, "Exa refused: payment_required")
            else:
                result = ProbeResult("exa", "unreachable", True, f"Exa answered HTTP {status}")
        except ProviderHalted as halt:
            reason = halt.reason_code.removeprefix("latched:")
            outcome: ProbeOutcome = "key_invalid" if reason == "forbidden" else "no_credit"
            result = ProbeResult("exa", outcome, True, f"Exa refused: {reason}")
        except Exception as error:  # noqa: BLE001 - any other failure means "not usable now"
            result = ProbeResult(
                "exa", "unreachable", True, f"{type(error).__name__}: {error}"[:300]
            )
        async with conn_factory() as conn:
            await drain_provider_calls(
                conn,
                raw=raw,
                ledger=ledger,
                artifacts=None,
                stamp=LedgerStamp(workspace_id=workspace_id),
            )
        return result

    return probe


def build_preflight(
    settings: Settings, secrets: Secrets, conn_factory: ConnFactory
) -> Callable[[str], Awaitable[PreflightReport]]:
    """The composed pre-flight a start or an operator route runs: one HTTP client per check."""
    exa_probe = build_exa_probe(secrets, conn_factory)

    async def preflight(workspace_id: str) -> PreflightReport:
        async with httpx.AsyncClient() as http:
            return await check_providers(
                secrets=secrets,
                settings=settings,
                workspace_id=workspace_id,
                http=http,
                exa_probe=exa_probe,
            )

    return preflight
