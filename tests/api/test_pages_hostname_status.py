from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from clue_api.dns_observe import DnsObservation
from clue_api.pages_hostname_status import ProviderState, derive_status

T0 = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
TARGET = "pages.cluehq.ai"
OK_PROVIDER = ProviderState(
    status="active", ssl_status="active", verification_errors=(), ssl_validation_errors=()
)
PENDING_PROVIDER = ProviderState(
    status="pending",
    ssl_status="pending_validation",
    verification_errors=(),
    ssl_validation_errors=(),
)


def _obs(cname: str | None, *txt: str, error: str | None = None) -> DnsObservation:
    return DnsObservation(cname=cname, txt_values=tuple(txt), error=error)


@pytest.mark.parametrize(
    ("observation", "provider", "now", "status", "code"),
    [
        (_obs(None), PENDING_PROVIDER, T0, "pending_dns", None),
        (_obs("elsewhere.example"), PENDING_PROVIDER, T0, "error", "cname_incorrect"),
        (_obs(TARGET), PENDING_PROVIDER, T0, "verifying_ownership", None),
        (
            _obs(TARGET),
            OK_PROVIDER,
            T0,
            "verifying_ownership",
            None,
        ),  # our TXT rule beats Cloudflare's active
        (_obs(TARGET), PENDING_PROVIDER, T0 + timedelta(minutes=31), "error", "txt_missing"),
        (_obs(TARGET, "tok"), PENDING_PROVIDER, T0, "issuing_certificate", None),
        (
            _obs(TARGET, "tok"),
            ProviderState("active", "pending_validation", (), ()),
            T0,
            "issuing_certificate",
            None,
        ),
        (_obs(TARGET, "tok"), OK_PROVIDER, T0, "active", None),
        (
            _obs(TARGET, "tok"),
            ProviderState(
                "pending", "pending_validation", (), ("CAA record at acme.com prevents issuance",)
            ),
            T0,
            "error",
            "caa_blocked",
        ),
        (
            _obs(TARGET, "tok"),
            ProviderState(
                "pending",
                "pending_validation",
                ("Custom hostname already exists elsewhere (1034)",),
                (),
            ),
            T0,
            "error",
            "provider_error",
        ),
        (
            _obs(TARGET, "tok"),
            ProviderState("moved", "active", (), ()),
            T0,
            "error",
            "verification_expired",
        ),
        (_obs(TARGET, "tok"), None, T0, "error", "verification_expired"),
        (_obs(None, error="SERVFAIL"), PENDING_PROVIDER, T0, "error", "provider_error"),
    ],
)
def test_ladder(
    observation: DnsObservation,
    provider: ProviderState | None,
    now: datetime,
    status: str,
    code: str | None,
) -> None:
    decision = derive_status(
        observation=observation,
        provider=provider,
        cname_target=TARGET,
        expected_txt_value="tok",
        connected_at=T0,
        now=now,
    )
    assert (decision.status, decision.error_code) == (status, code)
    assert (decision.error_detail is not None) == (code is not None)


def test_cname_comparison_ignores_case_and_trailing_dot() -> None:
    decision = derive_status(
        observation=_obs("Pages.CluehQ.ai.", "tok"),
        provider=OK_PROVIDER,
        cname_target=TARGET,
        expected_txt_value="tok",
        connected_at=T0,
        now=T0,
    )
    assert decision.status == "active"
