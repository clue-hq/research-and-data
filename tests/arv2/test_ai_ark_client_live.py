"""The AI Ark client against the real API — Global Constraint 3: no replay, no mocked bodies.

Six paid calls, two accounts (Global Constraint 11's answer keys), roughly 3.2 credits a run: a
company lookup, a name-scoped person lookup and an email export for Zafran Security and for
Probook. The last test audits what the other six spent and how far apart they ran, which is why
they share one client — pacing is per-client state, and AI Ark rate-limits harder than it
documents.

**This suite is slow on purpose.** The 10.5 s gap between calls means the six calls alone take
about a minute; that is the provider's rate limit being honoured, not a hang.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from clue_api.arv2.ai_ark_client import (
    BIRTH_DATE_KEYS,
    COMPANY_CREDITS_PER_RESULT,
    PERSON_CREDITS_PER_RESULT,
    AiArkClient,
)
from clue_api.arv2.calls import CallResult, ProviderCaller
from clue_api.arv2.sinks import FileRawSink, JsonlLedger
from clue_api.arv2.transport import HttpxTransport
from clue_config import Secrets, Settings
from tests.arv2.conftest import require_secret

ZAFRAN_DOMAIN = "zafran.io"
ZAFRAN_PERSON_VARIANTS = ("Nick Fisher", "Nicholas Fisher")
ZAFRAN_PERSON_URL = "https://www.linkedin.com/in/nicholastfisher"

PROBOOK_DOMAIN = "probook.ai"
PROBOOK_PERSON_VARIANTS = ("Mark Hoffman",)
PROBOOK_PERSON_SLUG = "/in/mark-hoffman-582a5741"
PROBOOK_EXPORT_URL = "https://www.linkedin.com/in/kibrady12"

#: Every verdict :func:`~clue_api.arv2.ai_ark_client.email_verdict` may return. The live tests
#: assert membership rather than a specific value: which one a real mailbox earns today is the
#: provider's answer, not ours, and pinning it would make the suite fail on a domain's MX change.
VERDICTS = ("verified_smtp", "catch_all_valid", "not_found")

EXPECTED_CALLS = 6


@dataclass(frozen=True)
class _Observation:
    """One live call: what came back and what it should have cost."""

    label: str
    result: CallResult
    expected_credits: Decimal


@pytest.fixture(scope="session")
def ai_ark_client(arv2_raw_root: Path, live_secrets: Secrets) -> AiArkClient:
    """One client for the whole module, so its pacing spans every call in the run.

    The conftest ``make_caller`` factory is function-scoped, and a per-test client would reset the
    pacing clock between tests — six calls in quick succession is exactly the pattern that drew
    429s on the free tier (contract notes §7 item 2). The caller is therefore built here, writing
    to the same on-disk raw sink and JSONL ledger every other ARV2 live test uses.
    """
    require_secret(live_secrets, "ai_ark_api_key")
    api_key = live_secrets.ai_ark_api_key
    assert api_key is not None
    caller = ProviderCaller(
        transport=HttpxTransport(),
        raw_sink=FileRawSink(arv2_raw_root / "raw"),
        ledger=JsonlLedger(arv2_raw_root / "ledger.jsonl"),
        now=lambda: datetime.now(UTC),
    )
    return AiArkClient(caller, api_key, min_gap_s=Settings().arv2_ai_ark_min_gap_s)


@pytest.fixture(scope="session")
def observations() -> list[_Observation]:
    """What each call returned, cost and cited — read by the audit test at the end."""
    return []


def _observe(
    observations: list[_Observation],
    client: AiArkClient,
    label: str,
    expected_credits: Decimal,
) -> CallResult:
    result = client.last_call
    assert result is not None, "the client did not record a call"
    observations.append(_Observation(label, result, expected_credits))
    return result


def _sent_at(rows: dict[str, dict[str, object]], result: CallResult) -> datetime:
    """When the provider actually saw this call, read from its pre-wire ledger row.

    The estimate row is written after pacing and immediately before the request goes out (law 2),
    so it is the only honest clock for "how far apart were these calls". A timestamp taken in the
    test would sit on the wrong side of the pacing sleep and read the gap as zero.
    """
    assert result.raw_ref is not None
    call_id = json.loads(Path(result.raw_ref).read_text(encoding="utf-8"))["call_id"]
    estimates = [
        row for row in rows.values() if row["call_id"] == call_id and row["phase"] == "estimate"
    ]
    assert len(estimates) == 1, f"expected one estimate row for {call_id}, got {len(estimates)}"
    return datetime.fromisoformat(str(estimates[0]["recorded_at"]))


def _assert_no_birth_date_on_disk(result: CallResult) -> None:
    """Appendix A law 3, checked where it matters: the bytes that actually got persisted.

    ``profile.birth_date`` is a real key in AI Ark bodies (present, usually null), so this is not
    a vacuous scan — an unscrubbed export record would contain the string.
    """
    assert result.raw_ref is not None
    saved = Path(result.raw_ref).read_text(encoding="utf-8")
    for key in BIRTH_DATE_KEYS:
        assert key not in saved, f"{key} survived into {result.raw_ref}"


# -- Zafran Security ---------------------------------------------------------------------------


def test_zafran_is_found_by_its_domain(
    ai_ark_client: AiArkClient, observations: list[_Observation]
) -> None:
    """The display name lives at ``summary.name``; a client reading ``name`` would see nothing."""
    company = ai_ark_client.company_by_domain(ZAFRAN_DOMAIN)
    result = _observe(
        observations,
        ai_ark_client,
        "zafran-company",
        COMPANY_CREDITS_PER_RESULT if company is not None else Decimal(0),
    )

    assert result.response.status == 200
    body = result.json()
    assert isinstance(body, dict)
    assert body["totalElements"] == 1

    assert company is not None
    assert company.name is not None and "Zafran" in company.name
    assert company.domain == ZAFRAN_DOMAIN
    assert company.linkedin is not None and "linkedin.com/company/" in company.linkedin


def test_nick_fisher_is_found_by_name_at_zafran(
    ai_ark_client: AiArkClient, observations: list[_Observation]
) -> None:
    """Name variants plus the domain: the target-lock that turns a common name into one person."""
    people = ai_ark_client.people_by_name(list(ZAFRAN_PERSON_VARIANTS), ZAFRAN_DOMAIN)
    result = _observe(
        observations,
        ai_ark_client,
        "zafran-people",
        PERSON_CREDITS_PER_RESULT * len(people),
    )

    assert result.response.status == 200
    matches = [
        person
        for person in people
        if person.linkedin_url is not None
        and person.linkedin_url.rstrip("/").endswith("/in/nicholastfisher")
    ]
    assert matches, f"no /in/nicholastfisher among {[p.linkedin_url for p in people]}"
    # 0.5 credit per record returned is a fact about the page, so the page carries it.
    assert people.cost.cost_source == "metered"
    assert people.cost.credits == PERSON_CREDITS_PER_RESULT * len(people)
    assert people.cost.ledger_row_id == result.ledger_row_id
    person = matches[0]
    assert person.current_company is not None and "Zafran" in person.current_company
    assert person.full_name is not None


def test_nick_fishers_email_exports_with_a_graded_verdict(
    ai_ark_client: AiArkClient, observations: list[_Observation]
) -> None:
    """The export's product is the graded email block, and a raw record with no birth date in it."""
    export = ai_ark_client.export_email(ZAFRAN_PERSON_URL)
    result = _observe(
        observations,
        ai_ark_client,
        "zafran-export",
        Decimal("1.0") if export.found else Decimal("0.5"),
    )

    assert result.response.status == 200
    assert export.verdict in VERDICTS
    assert export.raw_email_block, "the export returned no email block at all"
    if export.found:
        assert export.address is not None and "@" in export.address
        assert export.status is not None and export.domain_type is not None

    _assert_no_birth_date_on_disk(result)


# -- Probook -----------------------------------------------------------------------------------


def test_probook_is_found_by_its_domain(
    ai_ark_client: AiArkClient, observations: list[_Observation]
) -> None:
    company = ai_ark_client.company_by_domain(PROBOOK_DOMAIN)
    result = _observe(
        observations,
        ai_ark_client,
        "probook-company",
        COMPANY_CREDITS_PER_RESULT if company is not None else Decimal(0),
    )

    assert result.response.status == 200
    assert company is not None
    assert company.domain == PROBOOK_DOMAIN
    assert company.name is not None


def test_mark_hoffman_is_found_by_name_at_probook(
    ai_ark_client: AiArkClient, observations: list[_Observation]
) -> None:
    """The canary's same-name check: 464 unscoped "Mark Hoffman"s, one once the domain is added."""
    people = ai_ark_client.people_by_name(list(PROBOOK_PERSON_VARIANTS), PROBOOK_DOMAIN)
    result = _observe(
        observations,
        ai_ark_client,
        "probook-people",
        PERSON_CREDITS_PER_RESULT * len(people),
    )

    assert result.response.status == 200
    slugs = [person.linkedin_url for person in people]
    assert any(
        url is not None and url.rstrip("/").endswith(PROBOOK_PERSON_SLUG) for url in slugs
    ), f"no {PROBOOK_PERSON_SLUG} among {slugs}"


def test_kate_blumbergs_email_exports_with_a_graded_verdict(
    ai_ark_client: AiArkClient, observations: list[_Observation]
) -> None:
    """The address Apollo missed (contract notes §7 check b), graded rather than flattened."""
    export = ai_ark_client.export_email(PROBOOK_EXPORT_URL)
    result = _observe(
        observations,
        ai_ark_client,
        "probook-export",
        Decimal("1.0") if export.found else Decimal("0.5"),
    )

    assert result.response.status == 200
    assert export.verdict in VERDICTS
    _assert_no_birth_date_on_disk(result)


# -- the audit ---------------------------------------------------------------------------------


def test_every_call_was_paced_and_ledgered_at_its_result_count_price(
    observations: list[_Observation], arv2_raw_root: Path
) -> None:
    """Runs last: the six calls above are its subject.

    Two properties the individual tests cannot check for themselves — that the ledger charged
    result-count arithmetic rather than the pre-spend estimate, and that no two calls were sent
    inside the provider's pacing window.
    """
    assert len(observations) == EXPECTED_CALLS, "an earlier live call did not complete"

    rows = {
        row["row_id"]: row
        for row in (
            json.loads(line)
            for line in (arv2_raw_root / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        )
    }

    for observed in observations:
        row = rows[observed.result.ledger_row_id]
        assert row["phase"] == "result", observed.label
        assert row["outcome"] == "ok", observed.label
        assert row["provider"] == "ai_ark", observed.label
        assert row["raw_ref"] == observed.result.raw_ref, observed.label
        assert Decimal(str(row["credits"])) == observed.expected_credits, observed.label
        assert observed.result.cost.credits == observed.expected_credits, observed.label
        assert row["extras"]["cost_source"] == "metered", (
            f"{observed.label}: anything but `metered` means the ledger fell back to the "
            "estimate, so the cost reader failed"
        )
        assert observed.result.call_cost.cost_source == "metered", observed.label
        assert observed.result.call_cost.credits == observed.expected_credits, observed.label
        assert observed.result.call_cost.ledger_row_id == row["row_id"], observed.label
        assert Decimal(str(row["cost_usd"])) == Decimal(0), "AI Ark bills credits, not dollars"

    min_gap_s = Settings().arv2_ai_ark_min_gap_s
    sent = [_sent_at(rows, observed.result) for observed in observations]
    gaps = [
        (later - earlier).total_seconds() for earlier, later in zip(sent, sent[1:], strict=False)
    ]
    assert all(gap >= min_gap_s for gap in gaps), (
        f"calls were sent {[round(gap, 2) for gap in gaps]} s apart; the floor is {min_gap_s}"
    )
