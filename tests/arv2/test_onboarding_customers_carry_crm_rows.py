"""An onboarding refresh of ``proof/customers.md`` keeps the rows the CRM analysis wrote (R-4.5).

CRM rows are the rows whose Source names a CRM (``CRM: HubSpot …``). The refresh keeps them and
merges the website's findings around them by domain: one row per domain, the web row kept and the
CRM note added to its Source when both found the same company.
"""

# ruff: noqa: E501 -- the fixture is a real Markdown table, kept on one line per row
from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from clue_api.arv2.onboarding_documents import (
    CustomerRow,
    crm_customer_rows,
    existing_customers_document,
)
from tests.arv2.test_onboarding_documents import _CHECKS, AS_OF, _customers_run
from tests.arv2.test_onboarding_driver import FakeStore, _all_answers, _context, _handler

#: A version the CRM analysis wrote: one website row, one CRM-only row, one CRM row sharing a
#: domain with the website (Stripe), one CRM row with no domain, and a pipe in a quote.
_PREVIOUS = """# Existing customers

## Customers

| Customer | Domains | Domain check | How they buy | Evidence | Quote | Source |
|---|---|---|---|---|---|---|
| Wynwood House | wynwoodhouse.us | wynwoodhouse.us: unconfirmed | direct | case_study | moved \\| fast | https://conduit.ai/x |
| Acme Freight | acmefreight.test |  | direct | closed-won deal | Closed Won 2026-08-14 | CRM: HubSpot (closed 2026-08-14) |
| Stripe | stripe.com |  | direct | closed-won deal |  | CRM: HubSpot (closed 2026-07-02) |
| Nameless Co | no domain given |  | direct | closed-won deal |  | CRM: Salesforce (closed 2026-06-30) |

Seller's own domains: altcarbon.com
"""


def _table_rows(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith("| ") and "---" not in line][1:]


def test_parser_reads_only_crm_rows() -> None:
    rows = crm_customer_rows(_PREVIOUS)
    assert [row.customer for row in rows] == ["Acme Freight", "Stripe", "Nameless Co"]
    assert rows[0] == CustomerRow(
        customer="Acme Freight",
        domains=("acmefreight.test",),
        domain_check="",
        how_they_buy="direct",
        evidence="closed-won deal",
        quote="Closed Won 2026-08-14",
        source="CRM: HubSpot (closed 2026-08-14)",
    )
    assert rows[2].domains == ("no domain given",)


def test_parser_finds_columns_by_name_and_ignores_other_tables() -> None:
    reordered = (
        "| Source | Customer | Domains |\n|---|---|---|\n"
        "| CRM: HubSpot | Acme | acme.test, ACME.io |\n"
        "| https://x.test | Web Co | web.test |\n\n"
        "| Metric | Value |\n|---|---|\n| CRM: wins | 14 |\n"
    )
    rows = crm_customer_rows(reordered)
    assert [(row.customer, row.domains, row.quote) for row in rows] == [
        ("Acme", ("acme.test", "acme.io"), "")
    ]
    assert crm_customer_rows("# Existing customers\n\n_Not established._\n") == []


def test_refresh_keeps_crm_only_customers() -> None:
    body = existing_customers_document(
        _customers_run(),
        company_domain="altcarbon.com",
        as_of=AS_OF,
        checks=_CHECKS,
        carried_rows=crm_customer_rows(_PREVIOUS),
    ).body
    names = [row.split(" | ")[0].removeprefix("| ") for row in _table_rows(body)]
    # web rows (Wynwood House, Stripe) and CRM-only rows, sorted by name, Stripe once
    assert names == ["Acme Freight", "Nameless Co", "Stripe", "Wynwood House"]
    assert "| Acme Freight | acmefreight.test |" in body
    assert "CRM: Salesforce (closed 2026-06-30)" in body
    # the refreshed document still carries every CRM row for the next refresh
    assert [row.customer for row in crm_customer_rows(body)] == [
        "Acme Freight",
        "Nameless Co",
        "Stripe",
    ]


def test_shared_domain_keeps_one_row_with_both_sources() -> None:
    body = existing_customers_document(
        _customers_run(),
        company_domain="altcarbon.com",
        as_of=AS_OF,
        checks=_CHECKS,
        carried_rows=crm_customer_rows(_PREVIOUS),
    ).body
    stripe = [row for row in _table_rows(body) if row.startswith("| Stripe |")]
    assert len(stripe) == 1
    # the website's row (its domain check and source) with the CRM note added to its Source
    assert "stripe.com: confirmed" in stripe[0]
    assert stripe[0].endswith(
        "| https://altcarbon.com/press-releases/frontier · CRM: HubSpot (closed 2026-07-02) |"
    )
    # carrying it again does not repeat the note
    again = existing_customers_document(
        _customers_run(),
        company_domain="altcarbon.com",
        as_of=AS_OF,
        checks=_CHECKS,
        carried_rows=crm_customer_rows(body),
    ).body
    assert again.count("CRM: HubSpot (closed 2026-07-02)") == 1


def test_no_existing_document_behaves_as_today() -> None:
    today = existing_customers_document(
        _customers_run(), company_domain="altcarbon.com", as_of=AS_OF, checks=_CHECKS
    )
    carried_nothing = existing_customers_document(
        _customers_run(),
        company_domain="altcarbon.com",
        as_of=AS_OF,
        checks=_CHECKS,
        carried_rows=[],
    )
    assert carried_nothing.body == today.body
    failed = existing_customers_document(
        _customers_run(status="failed"),
        company_domain="altcarbon.com",
        as_of=AS_OF,
        checks={},
        carried_rows=crm_customer_rows(_PREVIOUS),
    ).body
    # a failed web run still keeps the CRM rows
    assert "Acme Freight" in failed and "_Not established._\n\nSeller" not in failed


def test_the_driver_carries_the_current_versions_crm_rows() -> None:
    reads: list[dict[str, Any]] = []

    async def current_document(conn: Any, **kw: Any) -> str | None:
        reads.append(kw)
        return _PREVIOUS

    handler = _handler(_all_answers(), FakeStore(), current_document=current_document)
    asyncio.run(handler.handle(_context(uuid4())))

    assert [read["path"] for read in reads] == ["proof/customers.md"]
    bodies = handler._artifacts.bodies  # type: ignore[attr-defined]
    body = next(b for b in bodies if b"# Existing customers" in b).decode()
    assert "| Acme Freight | acmefreight.test |" in body
    assert "| Wynwood House |" in body


def test_a_failed_read_fails_the_customers_step_rather_than_dropping_rows() -> None:
    async def current_document(conn: Any, **kw: Any) -> str | None:
        raise RuntimeError("storage down")

    store = FakeStore()
    asyncio.run(
        _handler(_all_answers(), store, current_document=current_document).handle(_context(uuid4()))
    )
    assert store.landed("customers")["status"] == "failed"
