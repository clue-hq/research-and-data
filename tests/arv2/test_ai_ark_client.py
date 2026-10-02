"""The AI Ark client's pure rules — the shape laws that must hold before any wire is touched.

Global Constraint 3 allows no mocked provider bodies, and none are used here: every function
under test is pure over a hand-written value, and the pre-wire refusals are proven by an
:class:`~clue_api.arv2.transport.ScriptedTransport` with an **empty script**. That is not a
stand-in for a provider — it is the assertion. An empty script raises ``AssertionError`` on any
request, so a test that passes has proved the refusal happened before the wire, not after it.
"""

from __future__ import annotations

import inspect
from dataclasses import fields
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr

from clue_api.arv2.ai_ark_client import (
    MAX_PEOPLE_PAGE_SIZE,
    PERSON_CREDITS_PER_RESULT,
    AiArkClient,
    AiArkCompany,
    AiArkEmailExport,
    AiArkPeople,
    ai_ark_halt_rule,
    company_from_record,
    email_export_from_record,
    email_verdict,
    export_cost_reader,
    person_from_record,
    scrub_birth_dates,
)
from clue_api.arv2.calls import CallCost, CallResult, CostReading, ProviderCaller
from clue_api.arv2.sinks import MemoryLedger, MemoryRawSink
from clue_api.arv2.transport import HttpResponse, ScriptedTransport

#: The three email blocks the provider actually produces, transcribed by hand from the canary and
#: the one-account run: a confirmed mailbox, a catch-all domain, and a miss.
VERIFIED_SMTP_BLOCK: dict[str, Any] = {
    "address": "vari@zafran.io",
    "mx": {"record": "aspmx.l.google.com", "google": False, "found": True, "provider": "g-suite"},
    "domainType": "SMTP",
    "status": "VALID",
    "subStatus": "EMPTY",
    "date": "2026-08-31T07:51:52.000461",
    "free": False,
    "generic": False,
    "found": True,
}
CATCH_ALL_BLOCK: dict[str, Any] = {
    "address": "kate@probook.ai",
    "mx": {"record": "smtp.google.com", "google": False, "found": True, "provider": "g-suite"},
    "domainType": "CATCH_ALL",
    "status": "VALID",
    "subStatus": "EMPTY",
    "date": "2026-08-29T21:01:47.000829",
    "free": False,
    "generic": False,
    "found": True,
}
NOT_FOUND_BLOCK: dict[str, Any] = {
    "address": None,
    "mx": {"record": None, "google": False, "found": False, "provider": None},
    "domainType": "UNKNOWN",
    "status": "INVALID",
    "subStatus": "MAILBOX_NOT_FOUND",
    "date": "2026-08-29T21:02:11.000004",
    "free": False,
    "generic": False,
    "found": False,
}


def _offline_client() -> tuple[AiArkClient, ScriptedTransport]:
    """A client whose transport has nothing scripted, so any request at all fails the test."""
    transport = ScriptedTransport([])
    caller = ProviderCaller(
        transport=transport,
        raw_sink=MemoryRawSink(),
        ledger=MemoryLedger(),
        now=lambda: datetime.now(UTC),
    )
    client = AiArkClient(caller, SecretStr("unused-in-this-test"), min_gap_s=0.0)
    return client, transport


# -- the size cap ------------------------------------------------------------------------------


def test_a_people_page_bigger_than_three_is_refused_before_the_wire() -> None:
    """The cap is a spend law: 0.5 credits per person means a big page is a roster by stealth."""
    client, transport = _offline_client()

    with pytest.raises(ValueError, match="size must be <= 3"):
        client.people_by_name(["Nick Fisher"], "zafran.io", size=4)

    assert transport.requests == [], "the refusal must happen before anything is sent"


def test_the_default_page_size_is_the_cap() -> None:
    """The caller who passes nothing gets the cap, not some larger convenience default."""
    default = inspect.signature(AiArkClient.people_by_name).parameters["size"].default
    assert default == MAX_PEOPLE_PAGE_SIZE == 3


# -- the empty-variants refusal ----------------------------------------------------------------


@pytest.mark.parametrize("variants", [[], [""], ["   ", "\n"]])
def test_a_people_search_with_no_usable_name_is_refused(variants: list[str]) -> None:
    """There is no domain-roster method by construction, and a blank name would be one."""
    client, transport = _offline_client()

    with pytest.raises(ValueError, match="at least one non-blank name"):
        client.people_by_name(variants, "zafran.io")

    assert transport.requests == []


@pytest.mark.parametrize("domain", ["", "   "])
def test_a_people_search_with_no_domain_is_refused(domain: str) -> None:
    """An unscoped name search is the same-name trap: 464 "Mark Hoffman"s, one of them right."""
    client, transport = _offline_client()

    with pytest.raises(ValueError, match="domain must be a non-blank string"):
        client.people_by_name(["Mark Hoffman"], domain)

    assert transport.requests == []


def test_a_company_lookup_with_no_domain_is_refused() -> None:
    client, transport = _offline_client()

    with pytest.raises(ValueError, match="domain must be a non-blank string"):
        client.company_by_domain("  ")

    assert transport.requests == []


def test_an_export_with_no_url_is_refused() -> None:
    client, transport = _offline_client()

    with pytest.raises(ValueError, match="linkedin_url must be a non-blank string"):
        client.export_email("")

    assert transport.requests == []


# -- verdict mapping ---------------------------------------------------------------------------


def test_a_valid_smtp_mailbox_is_verified() -> None:
    assert email_verdict(VERIFIED_SMTP_BLOCK) == "verified_smtp"


def test_a_valid_catch_all_domain_is_not_a_verified_mailbox() -> None:
    """``VALID`` on a catch-all domain means the domain accepts everything, not that Kate exists."""
    assert email_verdict(CATCH_ALL_BLOCK) == "catch_all_valid"


def test_an_invalid_address_is_not_found() -> None:
    assert email_verdict(NOT_FOUND_BLOCK) == "not_found"


def test_an_absent_email_block_grades_as_not_found() -> None:
    """The honest empty: an export that returned no email block claims nothing."""
    assert email_verdict({}) == "not_found"


def test_the_verdict_is_case_insensitive_on_both_fields() -> None:
    assert email_verdict({"status": "valid", "domainType": "smtp"}) == "verified_smtp"


def test_the_export_reader_keeps_the_whole_email_block_and_its_metadata() -> None:
    export = email_export_from_record(
        {
            "profile": {"full_name": "Vari Kaur", "title": "Head of Growth Marketing"},
            "position_groups": [{"company": {"name": "Zafran Security"}}],
            "certifications": [{"name": "Learning Kubernetes", "authority": "LinkedIn"}],
            "email": {"state": "DONE", "output": [VERIFIED_SMTP_BLOCK]},
        }
    )

    assert export.address == "vari@zafran.io"
    assert export.verdict == "verified_smtp"
    assert export.domain_type == "SMTP"
    assert export.sub_status == "EMPTY"
    assert export.mx_record == "aspmx.l.google.com"
    assert export.mx_provider == "g-suite"
    assert (export.mx_found, export.mx_google) == (True, False)
    assert export.free is False
    assert export.generic is False
    assert export.found is True
    assert export.checked_at == "2026-08-31T07:51:52.000461"
    assert export.full_name == "Vari Kaur"
    assert export.title == "Head of Growth Marketing"
    assert export.current_company == "Zafran Security"
    assert export.certifications[0]["name"] == "Learning Kubernetes"
    assert export.raw_email_block == {"state": "DONE", "output": [VERIFIED_SMTP_BLOCK]}


# -- the birth-date scrubber -------------------------------------------------------------------


def test_the_scrubber_drops_a_nested_birth_date_and_nothing_else() -> None:
    """Law 3, at the depth the provider actually puts it: ``content[].profile.birth_date``."""
    body = {
        "content": [
            {
                "id": "abc",
                "profile": {
                    "full_name": "Vari Kaur",
                    "birth_date": {"year": 1988, "month": 4},
                    "title": "Head of Growth Marketing",
                },
            }
        ],
        "totalElements": 1,
    }

    scrubbed = scrub_birth_dates(body)

    assert scrubbed == {
        "content": [
            {
                "id": "abc",
                "profile": {"full_name": "Vari Kaur", "title": "Head of Growth Marketing"},
            }
        ],
        "totalElements": 1,
    }


@pytest.mark.parametrize("key", ["birth_date", "birthDate", "birthday"])
def test_every_spelling_of_a_birth_date_is_dropped(key: str) -> None:
    scrubbed = scrub_birth_dates({"profile": {key: "1988-04-01", "full_name": "Vari Kaur"}})
    assert scrubbed == {"profile": {"full_name": "Vari Kaur"}}


def test_the_scrubber_leaves_a_body_with_no_birth_date_byte_identical() -> None:
    """It replaces the response for the whole call, so over-scrubbing would corrupt the record."""
    body = {"content": [{"summary": {"name": "Zafran Security"}}], "totalElements": 1}
    assert scrub_birth_dates(body) == body


def test_the_scrubber_passes_scalars_and_lists_through() -> None:
    assert scrub_birth_dates([1, "two", None, {"birthday": "x", "keep": True}]) == [
        1,
        "two",
        None,
        {"keep": True},
    ]


# -- the halt rule -----------------------------------------------------------------------------


@pytest.mark.parametrize("status", [402, 403])
def test_a_refusal_status_halts_the_provider(status: int) -> None:
    assert ai_ark_halt_rule(HttpResponse(status=status)) == "ai_ark_credit_exhausted_or_denied"


def test_a_four_hundred_naming_credit_halts_the_provider() -> None:
    """AI Ark reports exhaustion in prose; the status alone would not show it."""
    response = HttpResponse(status=400, body=b'{"message":"Not enough CREDITS on this account"}')
    assert ai_ark_halt_rule(response) == "ai_ark_credit_exhausted_or_denied"


def test_a_successful_body_mentioning_credit_does_not_halt() -> None:
    """A company whose description says "credit" is not a billing failure."""
    response = HttpResponse(status=200, body=b'{"content":[{"summary":{"name":"Credit Karma"}}]}')
    assert ai_ark_halt_rule(response) is None


def test_an_ordinary_four_hundred_does_not_halt() -> None:
    response = HttpResponse(status=400, body=b'{"message":"both domain and name are required"}')
    assert ai_ark_halt_rule(response) is None


# -- the cost arithmetic -----------------------------------------------------------------------


def test_an_export_that_found_an_address_costs_a_whole_credit() -> None:
    response = HttpResponse(
        status=200, body=b'{"email":{"state":"DONE","output":[{"found":true}]}}'
    )
    assert export_cost_reader(response).credits == Decimal("1.0")


def test_an_export_that_found_nothing_costs_zero_under_the_current_contract() -> None:
    response = HttpResponse(
        status=200, body=b'{"email":{"state":"DONE","output":[{"found":false}]}}'
    )
    assert export_cost_reader(response).credits == Decimal("0")


def test_a_refused_export_costs_nothing_rather_than_the_estimate() -> None:
    """An explicit zero, not ``None``: ``None`` would make the wrapper bill the estimate."""
    reading = export_cost_reader(HttpResponse(status=404, body=b'{"message":"not found"}'))
    assert reading.credits == Decimal(0)


# -- record mapping ----------------------------------------------------------------------------


def test_the_company_reader_maps_the_nested_paths_the_provider_actually_uses() -> None:
    """The display name is ``summary.name``; there is no top-level ``name`` key to read."""
    company = company_from_record(
        {
            "id": "4d204374",
            "summary": {
                "name": "Zafran Security",
                "industry": "computer and network security",
                "staff": {"total": 167},
            },
            "link": {
                "domain": "zafran.io",
                "linkedin": "https://www.linkedin.com/company/zafran-security",
            },
            "financial": {"revenue": {"annual": {"amount": "10000000-25000000"}}},
            "technologies": [
                {"name": "google cloud", "category": "hosting"},
                {"name": "envoy", "category": "server"},
            ],
            "location": {"headquarter": {"city": "New York, New York"}},
        }
    )

    assert company.name == "Zafran Security"
    assert company.domain == "zafran.io"
    assert company.linkedin == "https://www.linkedin.com/company/zafran-security"
    assert company.industry == "computer and network security"
    assert company.employee_count == 167
    assert company.revenue == "10000000-25000000"
    assert company.technologies == ("google cloud", "envoy")
    assert company.location == {"city": "New York, New York"}


def test_the_person_reader_takes_the_domain_from_the_embedded_current_employer() -> None:
    """``position_groups[0].company`` carries no domain; the top-level ``company`` block does."""
    person = person_from_record(
        {
            "id": "5669ed27",
            "profile": {
                "full_name": "Nick Fisher",
                "title": "VP of Marketing",
                "headline": "VP Marketing at Zafran Security",
            },
            "link": {"linkedin": "https://www.linkedin.com/in/nicholastfisher"},
            "location": {"city": "New York"},
            "department": {"seniority": "vp"},
            "position_groups": [{"company": {"name": "Zafran Security"}}],
            "company": {"summary": {"name": "Zafran Security"}, "link": {"domain": "zafran.io"}},
        }
    )

    assert person.full_name == "Nick Fisher"
    assert person.title == "VP of Marketing"
    assert person.linkedin_url == "https://www.linkedin.com/in/nicholastfisher"
    assert person.current_company == "Zafran Security"
    assert person.current_company_domain == "zafran.io"
    assert person.ark_id == "5669ed27"
    assert person.department == {"seniority": "vp"}


def test_the_person_reader_takes_the_domain_when_the_two_blocks_share_a_linkedin_page() -> None:
    """The live Cogent record: the two blocks spell the name differently and are one company.

    ``position_groups[0].company.name`` is ``"Cogent"`` and ``company.summary.name`` is
    ``"Cogent Security"``. On the name alone the domain was refused and every Cogent person lost
    their lookup; the company URL both blocks carry says they are the same page.
    """
    person = person_from_record(
        {
            "profile": {"full_name": "Alexander Semien"},
            "position_groups": [
                {
                    "company": {
                        "name": "Cogent",
                        "url": "https://www.linkedin.com/company/cogentsecurity/",
                    }
                }
            ],
            "company": {
                "summary": {"name": "Cogent Security"},
                "link": {
                    "domain": "cogent.com",
                    "linkedin": "https://linkedin.com/company/cogentsecurity",
                },
            },
        }
    )

    assert person.current_company == "Cogent"
    assert person.current_company_domain == "cogent.com"


def test_the_person_reader_takes_the_domain_when_one_company_name_contains_the_other() -> None:
    """No URL on either block: a folded name inside the other is the same employer written short."""
    person = person_from_record(
        {
            "profile": {"full_name": "Alexander Semien"},
            "position_groups": [{"company": {"name": "Cogent"}}],
            "company": {
                "summary": {"name": "Cogent Security"},
                "link": {"domain": "cogent.com"},
            },
        }
    )

    assert person.current_company_domain == "cogent.com"


@pytest.mark.parametrize(
    ("position_name", "company_name"),
    [("Box", "Dropbox"), ("Meta", "Metabase")],
    ids=["box-in-dropbox", "meta-in-metabase"],
)
def test_a_name_merely_spelled_inside_another_is_not_the_same_employer(
    position_name: str, company_name: str
) -> None:
    """Containment is over whole words. Character containment would hand a mover the old
    employer's domain, and the caller compares that domain to the account — so a stale committee
    row would clear the employer lock and be researched under the wrong account."""
    person = person_from_record(
        {
            "profile": {"full_name": "Alexander Semien"},
            "position_groups": [{"company": {"name": position_name}}],
            "company": {
                "summary": {"name": company_name},
                "link": {"domain": f"{company_name.lower()}.com"},
            },
        }
    )

    assert person.current_company_domain is None


def test_a_different_company_page_and_an_unrelated_name_leave_the_domain_unknown() -> None:
    """Both rungs fail: a different company page, and neither name contains the other."""
    person = person_from_record(
        {
            "profile": {"full_name": "Alexander Semien"},
            "position_groups": [
                {
                    "company": {
                        "name": "Cogent",
                        "url": "https://www.linkedin.com/company/cogentsecurity",
                    }
                }
            ],
            "company": {
                "summary": {"name": "Some Prior Corp"},
                "link": {
                    "domain": "prior.example",
                    "linkedin": "https://www.linkedin.com/company/some-prior-corp",
                },
            },
        }
    )

    assert person.current_company_domain is None


def test_a_domain_from_a_different_company_is_not_attached_to_the_person() -> None:
    """Target-locking: a previous employer's domain on a mover would be a fabricated fact."""
    person = person_from_record(
        {
            "profile": {"full_name": "Nick Fisher"},
            "position_groups": [{"company": {"name": "Zafran Security"}}],
            "company": {
                "summary": {"name": "Some Prior Corp"},
                "link": {"domain": "prior.example"},
            },
        }
    )

    assert person.current_company == "Zafran Security"
    assert person.current_company_domain is None


# -- the cost every AI Ark return value carries -------------------------------------------------
#
# AI Ark's live suite cannot run today (the account answers 402, so every request halts the
# provider before a body exists). These cover the new result shapes without a wire: the money
# view is assembled from a hand-made ``CallResult``, exactly as the wrapper would hand one over.


def _call_result(credits: Decimal) -> CallResult:
    """A completed call as the wrapper returns it, metered in credits like every AI Ark call."""
    cost = CallCost(
        cost_usd=Decimal(0),
        credits=credits,
        media_seconds=0,
        cost_source="metered",
        ledger_row_id="row-1",
        raw_ref="memory:0",
        provider="ai_ark",
        operation="v1/people",
    )
    return CallResult(
        response=HttpResponse(200, {}, b"{}"),
        latency_ms=1,
        attempts=1,
        raw_ref="memory:0",
        raw_refs=("memory:0",),
        ledger_row_id="row-1",
        cost=CostReading(credits=credits),
        over_ceiling=False,
        call_cost=cost,
    )


def test_a_people_page_carries_the_pages_cost_and_no_person_carries_a_share_of_it() -> None:
    """0.5 credit **per record returned** is a fact about the page, not about anyone in it.

    A cost attached to each person would make a caller that sums its people over-count the run by
    the page size, which is the one arithmetic error this shape exists to make unrepresentable.
    """
    result = _call_result(PERSON_CREDITS_PER_RESULT * 2)
    records = [
        {"profile": {"full_name": "Nick Fisher"}},
        {"profile": {"full_name": "Sanaz Yashar"}},
    ]

    people = AiArkPeople(
        people=tuple(person_from_record(record) for record in records), cost=result.call_cost
    )

    assert people.cost is result.call_cost
    assert people.cost.credits == PERSON_CREDITS_PER_RESULT * 2
    assert people.cost.cost_source == "metered", "AI Ark bills by result count on every call"
    assert not any(hasattr(person, "cost") for person in people), (
        "a per-person cost would be double-counted once per record on the page"
    )


def test_a_people_page_iterates_and_measures_like_the_list_it_replaced() -> None:
    """Carrying the cost must not cost the caller their ``for`` loop."""
    people = AiArkPeople(
        people=(
            person_from_record({"profile": {"full_name": "Nick Fisher"}}),
            person_from_record({"profile": {"full_name": "Sanaz Yashar"}}),
        ),
        cost=_call_result(Decimal("1.0")).call_cost,
    )

    assert len(people) == 2
    assert [person.full_name for person in people] == ["Nick Fisher", "Sanaz Yashar"]
    assert people[0].full_name == "Nick Fisher"


def test_the_pure_record_mappers_leave_the_cost_unset_rather_than_inventing_one() -> None:
    """A mapper is handed a record, not a request. There is no ledger row to point at.

    ``None`` is the honest answer; a zero-cost :class:`CallCost` would name a row id that does
    not exist and claim a call nobody made.
    """
    company = company_from_record({"summary": {"name": "Zafran Security"}})
    export = email_export_from_record({"email": {"output": [VERIFIED_SMTP_BLOCK]}})
    person = person_from_record({"profile": {"full_name": "Nick Fisher"}})

    assert company.cost is None
    assert export.cost is None
    assert not hasattr(person, "cost"), "a person is one record on a page; the page holds the cost"


def test_every_ai_ark_result_type_has_somewhere_to_put_a_cost() -> None:
    """The uniform provision, asserted structurally: no return type is exempt.

    This is the guard against the change rotting — a new AI Ark result type added without a
    ``cost`` field fails here rather than at whatever tries to bill for it.
    """
    for result_type in (AiArkCompany, AiArkEmailExport, AiArkPeople):
        assert "cost" in {f.name for f in fields(result_type)}, result_type.__name__
