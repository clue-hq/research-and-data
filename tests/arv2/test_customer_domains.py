"""The customer domain check (spec 2026-10-16-discovery-excludes-seller-customers §4.2). Offline.

Exa gives each customer's domains; one GET of each homepage labels it ``confirmed`` when the page
names the company and ``unconfirmed`` otherwise. It never drops a domain. The live test that set
this up: Exa gave Wynwood House (a hospitality group) the domain ``wynwoodhouse.us``, whose site
belongs to a personal-care home in Pennsylvania.
"""

from __future__ import annotations

from clue_api.arv2.customer_domains import DomainCheck, check_domains, names_company
from clue_api.arv2.transport import HttpResponse, ScriptedTransport
from clue_spend.transport import TransportFailure
from tests.arv2.test_media_research import caller


def _page(title: str, text: str = "") -> HttpResponse:
    html = f"<html><head><title>{title}</title></head><body><p>{text}</p></body></html>"
    return HttpResponse(200, {"content-type": "text/html"}, html.encode())


def test_a_page_that_names_the_company_is_confirmed() -> None:
    wire = ScriptedTransport([_page("Casago - Vacation Rentals and Property Management")])
    checks = check_domains(caller(wire), [{"name": "Casago", "domains": ["casago.com"]}])
    assert checks == {
        "casago.com": DomainCheck("confirmed", "Casago - Vacation Rentals and Property Management")
    }
    assert wire.requests[0].url == "https://casago.com/"


def test_a_page_about_another_business_is_unconfirmed_and_kept() -> None:
    wire = ScriptedTransport([_page("Personal Care Communities | State College")])
    checks = check_domains(
        caller(wire), [{"name": "Wynwood House", "domains": ["wynwoodhouse.us"]}]
    )
    assert checks == {
        "wynwoodhouse.us": DomainCheck("unconfirmed", "Personal Care Communities | State College")
    }


def test_a_domain_that_does_not_answer_is_unconfirmed() -> None:
    wire = ScriptedTransport(
        [
            TransportFailure("connection refused"),
            HttpResponse(403, {"content-type": "text/html"}, b"<title>Access Denied</title>"),
        ]
    )
    checks = check_domains(
        caller(wire),
        [
            {"name": "Moxxi", "domains": ["moxxiproperty.com.au"]},
            {"name": "Marriott", "domains": ["marriott.com"]},
        ],
    )
    assert checks["moxxiproperty.com.au"] == DomainCheck("unconfirmed", None)
    assert checks["marriott.com"] == DomainCheck("unconfirmed", None)


def test_names_company_tolerates_case_spacing_and_suffixes() -> None:
    assert names_company("Mitsui O.S.K. Lines, Ltd.", "MOL - Mitsui O.S.K. Lines")
    assert names_company("HostGenius", "HostGenius · A private network for operators")
    assert names_company("Host Genius", "HostGenius · A private network for operators")
    assert names_company("The Flex", "Flexible Living, Made Easy | The Flex (Formerly Flex Living)")
    assert not names_company("Olala", "<html></html>")
    assert not names_company("Wynwood House", "Personal Care Communities | State College")


def test_each_domain_is_fetched_once() -> None:
    wire = ScriptedTransport([_page("Hilton Hotels & Resorts")])
    checks = check_domains(
        caller(wire),
        [
            {"name": "Hilton", "domains": ["hilton.com"]},
            {"name": "Hilton Garden Inn", "domains": ["hilton.com"]},
        ],
    )
    assert len(wire.requests) == 1
    assert checks["hilton.com"].status == "confirmed"


def test_a_short_name_inside_another_word_is_not_a_match() -> None:
    """The check errs towards unconfirmed: "Sage" is not named by a page that says "message"."""
    assert not names_company("Sage", "Our message is clear")
    assert not names_company("Olala", "Holalandia resorts")
    assert names_company("Sage", "Sage | Accounting software")
