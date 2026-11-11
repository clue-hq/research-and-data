"""find_handles reports what happened (review I5) and keeps only what it uses from PDL (review C1).

A People Data Labs failure is a named failure, not "no handles"; its out-of-credit or refused key
stops PDL for the job; a match carries PDL's likelihood; an Instagram check that fails is a
failure; and the PDL record is trimmed to the handle fields before anything is stored or read, so
personal emails, phones and birth dates are never saved.
"""

from __future__ import annotations

import json

from clue_api.footprint.handles import find_handles
from clue_api.footprint.pdl_client import pdl_person
from clue_spend.transport import HttpResponse
from tests.footprint.test_handles import PDL, PDL_MATCH, TOKEN, ig_profile, reply, wire

LINKEDIN = "https://www.linkedin.com/in/ada-example/"

#: A PDL match as PDL sends it: the handles we use, and personal data we must never keep.
FULL_MATCH = {
    "status": 200,
    "likelihood": 8,
    "data": {
        **PDL_MATCH["data"],
        "full_name": "ada example",
        "personal_emails": ["ada@home.example"],
        "recommended_personal_email": "ada@home.example",
        "mobile_phone": "+1 555 0100",
        "birth_date": "1980-01-01",
        "location_street_address": "1 Main St",
    },
}


def pdl_error(status, kind, message):
    body = {"status": status, "error": {"type": kind, "message": message}}
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(body).encode())


def not_on_instagram():
    body = {"success": True, "error": "not_found", "message": "Profile is unavailable on Instagram"}
    return reply(body, 404, "0")


def handles(caller, pdl=PDL, token=TOKEN):
    return find_handles(
        caller, token, pdl, name="Ada Example", company="Acme", linkedin_url=LINKEDIN
    )


def test_pdl_record_is_trimmed_before_it_is_stored_or_read():
    caller, _, _ = wire(HttpResponse(200, {}, json.dumps(FULL_MATCH).encode()))
    found = pdl_person(caller, PDL, name="Ada", company="Acme", linkedin_url=LINKEDIN)
    assert found.state == "matched" and found.likelihood == 8
    assert found.data == PDL_MATCH["data"]
    stored = b"".join(body for _, body in caller._raw_sink.records)
    for private in (
        b"personal_emails",
        b"ada@home.example",
        b"mobile_phone",
        b"birth_date",
        b"1 Main St",
    ):
        assert private not in stored


def test_pdl_failure_is_named_and_instagram_still_checked():
    caller, transport, _ = wire(
        pdl_error(429, "rate_limit_error", "Too many requests"),
        pdl_error(429, "rate_limit_error", "Too many requests"),
        reply(ig_profile(False)),
    )
    found, tally = handles(caller)
    assert [(h.platform, h.handle) for h in found] == [("instagram", "ada-example")]
    assert tally.state == "partial"
    assert any(
        "People Data Labs" in g and "429" in g and "Too many requests" in g for g in tally.gaps
    )


def test_pdl_out_of_credit_stops_pdl():
    caller, _, _ = wire(
        pdl_error(402, "payment_required", "You have hit your account maximum"),
        reply(ig_profile(False)),
    )
    found, tally = handles(caller)
    assert tally.stopped == {"pdl": "payment_required"} and tally.state == "partial"
    assert [h.platform for h in found] == ["instagram"]


def test_pdl_no_match_is_an_answer():
    caller, _, _ = wire(pdl_error(404, "not_found", "No records were found"), not_on_instagram())
    found, tally = handles(caller)
    assert found == [] and tally.state == "complete" and tally.gaps == []


def test_pdl_candidates_carry_the_likelihood():
    caller, _, _ = wire(
        HttpResponse(200, {}, json.dumps(FULL_MATCH).encode()),
        not_on_instagram(),
        not_on_instagram(),
        not_on_instagram(),
    )
    found, tally = handles(caller)
    assert [(h.platform, h.likelihood) for h in found] == [("x", 8), ("facebook", 8)]
    assert tally.state == "complete"


def test_instagram_check_failure_is_a_failure():
    caller, _, _ = wire(
        reply({"detail": {"message": "upstream"}}, 500, "0"), *[reply({}, 500, "0")] * 4
    )
    found, tally = handles(caller, pdl=None)
    assert found == [] and tally.state == "unavailable"
    assert any("Instagram" in g for g in tally.gaps)


def test_treg_out_of_credit_keeps_the_pdl_handles_and_stops_treg():
    out_of_credit = HttpResponse(
        402, {"content-type": "application/json", "X-Treg-Error": "1"}, b'{"detail": "x"}'
    )
    caller, transport, _ = wire(
        HttpResponse(200, {}, json.dumps(FULL_MATCH).encode()), out_of_credit
    )
    found, tally = handles(caller)
    assert [h.platform for h in found] == ["x", "facebook"]
    assert tally.stopped == {"treg": "payment_required"} and len(transport.requests) == 2


def test_no_treg_key_still_asks_pdl():
    caller, _, _ = wire(HttpResponse(200, {}, json.dumps(FULL_MATCH).encode()))
    found, tally = handles(caller, token=None)
    assert [h.platform for h in found] == ["x", "facebook"]
    assert tally.state == "complete" and any("Instagram" in g for g in tally.gaps)
