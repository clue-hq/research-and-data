"""The Exa client against the real API — Global Constraint 3: no replay, no mocked bodies.

Six calls, roughly $0.25 and 5–15 minutes: two searches and one contents fetch prove the cheap
instruments and the cost path; three deep-reasoning calls prove the expensive one, including the
Appendix A law 4 silent-fail guard and the product-catalog schema from
``ARV2-PRODUCT-CATALOG-CONTRACT.md`` §3 (the one request shape that can be rejected for its
``enum``, which is exactly why it is exercised live rather than asserted on paper).

The two dossier prompts are ported **verbatim** from the proof-of-concept scripts named in the
brief (``z5_exa_deep.py`` and ``step6_account_deep.py``). They are the paid-for artefacts: their
target lock, their same-name exclusions and their "write NOT FOUND" rule are what make the answer
gradeable, and a paraphrase would be testing a different prompt than the one the lane ships.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr

from clue_api.arv2.calls import CallCost, ProviderCaller
from clue_api.arv2.exa_client import (
    ExaClient,
    product_catalog_output_schema,
    report_output_schema,
)
from clue_config import Secrets
from tests.arv2.conftest import require_secret

JOB_BOARD_DOMAINS = ["jobs.ashbyhq.com", "boards.greenhouse.io", "jobs.lever.co"]

#: Global Constraint 11's answer key: Zafran's own site and a YouTube video Exa has indexed.
CONTENTS_URLS = ["https://zafran.io", "https://www.youtube.com/watch?v=avcD5WVLCYs"]


# -- the Zafran dossier prompt, verbatim from .context/arv2-one-account-aiark/z5_exa_deep.py ----

LOCK = """  Zafran Security (zafran.io), legal name "Zafran Security Ltd.", an AI-native
  threat-exposure-management cybersecurity company founded 2022 by Sanaz Yashar (CEO),
  Ben Seri (CTO) and Snir Havdala (CPO, since departed), HQ New York City with R&D in Tel Aviv,
  ~167 employees, $130.5M raised across 4 rounds, $60M Series C led by Menlo Ventures announced
  2025-12-02, plus a Cisco Investments strategic investment announced 2026-07-22.

EXCLUDE and name any same-name entity: "Zafran" is also a saffron/spice brand and the name of
several restaurants and food companies; there is also "Zafran Global". NONE of those are the
subject."""

ZAFRAN_SYSTEM = f"""\
You are a B2B account researcher producing an evidence-grounded dossier on ONE company
for a go-to-market team. Today's date is 2026-09-02.

TARGET LOCK — the ONLY subject is:
{LOCK}

RULES
  * Every factual assertion carries a VERBATIM quote and the URL it came from.
  * If you cannot find something, write "NOT FOUND". Never estimate, never infer a number, never
    fill a gap with a plausible guess. An honest NOT FOUND is a correct answer.
  * Distinguish what the company claims about itself from what a third party reports.
  * A LinkedIn/Tracxn/CB-Insights auto-estimate is an ESTIMATE — label it as one, never as fact.
  * Prefer primary sources: the company's own pages, its job postings, the funding wire release,
    the investors' announcements, the founders' own writing and posts.
  * Name every person with their exact title and the URL that names them. Never invent a person.
  * For anything about an acquisition/rumour, state explicitly whether it was CONFIRMED, DENIED or
    UNRESOLVED, and by whom, with the quote."""

ALREADY_KNOWN = """\
ALREADY ESTABLISHED (do NOT spend the budget re-deriving these; treat as given and
go find what is NOT here):
  - legal name "Zafran Security Ltd."; HQ New York, New York; founded 2022; 167 employees.
  - Funding rounds already known exactly: SEED 2024-03-28 $5.5M; VENTURE 2024-03-28 $25M;
    SERIES_B 2024-09-08 $40M (Cyberstarts, Cerca Partners, Penny Jar Capital);
    SERIES_C 2025-12-02 $60M (Menlo Ventures, Sequoia, Cyberstarts, Amex Ventures, PSP Growth,
    Vintage Investment Partners, Knollwood); total $130.5M; 9 investors.
  - Committee already known: Sanaz Yashar (Co-Founder & CEO), Ben Seri (Co-Founder & CTO),
    Nick Fisher (VP of Marketing, joined Apr 2024), Vari Kaur / Varinder Kaur (Head of Growth
    Marketing, joined May 2025, ex-Secureworks), Tom Anthony (SVP Global Sales),
    Rotem Peled-Dvir (SVP Finance).
  - Their live Ashby board (checked today, 2026-09-02) has 27 open reqs, including
    "Senior Manager, ABM & Integrated Campaigns" published 2026-06-17 (still listed = 77 days
    open), "Sr Technical Marketing Manager" published 2026-06-17, "Business Development
    Representative" (New York, filed under the MARKETING department) published 2026-08-19,
    "Director of Sales, Enterprise" published 2026-09-01, "Director of Alliances" published
    2026-09-01, "HR Business Partner" published 2026-09-01.
  - Website technologies detected: HubSpot-hosted pages, Zendesk mail (MX), Google Cloud,
    Amazon S3/Oregon, Envoy, Cloudflare. Corporate email MX is Google Workspace.
  - Named case studies exist on their own site (Lumen, a Fortune 500 financial institution,
    a pharma, a Fortune 1000 manufacturer, a Fortune 500 insurer, a Kenna replacement)."""

ZAFRAN_CHARTER = f"""\
Produce an exhaustive, cited markdown dossier on Zafran Security (zafran.io) covering:

1. WHAT THEY ACTUALLY SELL — the product in their own words, the exact buyer titles, the buying
   process they describe, deal size / pricing model if published anywhere, and how they position
   against Tenable, Wiz, Rapid7, Qualys, Kenna/Cisco and other exposure-management vendors. Quote.
2. FUNDING — confirm/extend the rounds listed as already known; find the Cisco Investments and
   Amex Ventures amounts if disclosed anywhere; the current total raised; valuation if reported;
   and any stated use of proceeds.
3. GO-TO-MARKET TEAM — every named marketing, sales, partnerships, RevOps and customer-success
   person with exact title and the URL naming them. Who reports to whom where stated. Any GTM seat
   that is vacant, newly filled, or recently departed (<12 months) — with dates.
4. HIRING, WITH QUOTES — for the marketing/GTM reqs, quote the parts of the job descriptions that
   describe HOW they find and reach target accounts (target account lists, account research,
   outbound, ABM, campaigns, field marketing, events, tooling they must operate), and quote the
   compensation ranges if published. Note anything open unusually long.
5. MARTECH / ABM / INTENT TOOLING — quote any evidence of: 6sense, Demandbase, Terminus,
   RollWorks, Mutiny, Folloze, Influ2, Madison Logic, ZoomInfo, Clay, Common Room, Gong,
   Salesforce, HubSpot, Marketo, Outreach, Salesloft, Apollo, LinkedIn Sales Navigator. Write
   NOT FOUND for each one you cannot evidence. Do not guess.
6. NAMED CUSTOMERS & PROOF — every customer named anywhere (their own case studies, press,
   partner pages, conference talks), plus every outcome metric with who claimed it.
7. OPERATIONAL PAIN & STRATEGIC MOVES — the constraints the company itself describes about its own
   business (not its customers' security pain): growth, hiring, category competition, partner
   motion, product gaps. Plus the moves it says it is making next.
8. TIMING EVENTS, newest first, each dated — anything in the last 9 months that changes their
   buying posture.
9. REPUTATION AND NEGATIVES — this section is REQUIRED and must not be skipped. Cover:
   (a) the July 2026 Calcalist/CTech report that Cisco was in talks to ACQUIRE Zafran "at a steep
   discount" (~$150M) and the subsequent Globes report that Cisco was INVESTING, not acquiring —
   state clearly which is the settled outcome, with quotes and URLs from BOTH, and label the
   acquisition story explicitly as REFUTED/NOT CONFIRMED if that is what the evidence shows;
   (b) the departure of co-founder/CPO Snir Havdala and where he went, with dates;
   (c) any reported slowing growth, ARR figures, layoffs, down-round, churn, security incident,
   lawsuit, negative analyst/customer review, or Glassdoor-style sentiment — with the source;
   (d) any critical or sceptical commentary about the category or the company.
   For every negative item, say who reported it and whether the company responded.
10. WHO THE HEAD OF GROWTH MARKETING'S TEAM IS — the ABM req reports to the Head of Growth
    Marketing (Vari Kaur). Find every other person on the marketing team by name and title, and
    any agency/contractor/vendor they publicly credit.

{ALREADY_KNOWN}
"""

ZAFRAN_HIGHLIGHTS_QUERY = (
    "Zafran Security go-to-market marketing leadership hiring funding customers "
    "Cisco acquisition rumour"
)


# -- the Probook dossier prompt, verbatim from .context/arv2-clue-sample-v3/step6_account_deep.py

PROBOOK_SYSTEM = """\
You are a B2B account researcher producing an evidence-grounded dossier on ONE company.

TARGET LOCK — the ONLY subject is:
  Probook, the AI operating system for home-services businesses (plumbing, HVAC, electrical),
  domain probook.ai, headquartered in New York, NY, founded 2024, co-founded by George Eliadis
  (CEO), Lewis Zhang (CTO) and Ben Cervantez. Raised a $34M Series A led by Andreessen Horowitz
  announced 2026-06-23, on top of a $6M seed led by Sequoia Capital.

EXCLUDE and explicitly name any same-name entity you encounter: ProBook is also a well-known HP
laptop line (HP ProBook), and there are unrelated "Probook"/"ProBook" bookkeeping, accounting and
booking-software products. NONE of those are the subject. If a source is about HP laptops or a
bookkeeping tool, say so and discard it.

RULES
  * Every factual assertion carries a verbatim quote and the URL it came from.
  * If you cannot find something, write "NOT FOUND" for it. Never estimate, never infer a number.
  * Distinguish what the company claims about itself from what a third party reports.
  * Prefer primary sources: probook.ai's own pages, the company's job postings, the funding wire
    release, the investors' announcement posts, the founders' own writing.
"""

PROBOOK_CHARTER = """Produce an exhaustive, cited markdown dossier on Probook (probook.ai) covering:

1. IDENTITY & DISAMBIGUATION — legal/operating name, HQ address, founding year, domain(s), company
   LinkedIn, and an explicit list of the same-name entities you excluded and why.
2. PRODUCT & TARGET VERTICAL — what the product actually does, the exact vertical it sells INTO,
   how fragmented that buyer base is (quote any count of US home-service businesses / contractors),
   what systems it integrates with (ServiceTitan and any others), pricing model if published.
3. TRACTION — named customers, number of locations/technicians served, revenue or ARR if stated,
   per-customer outcome metrics, and who claimed each number (company vs investor vs press).
4. FUNDING — every round with exact amount, date, lead investor and participants; total raised;
   any stated use of proceeds or growth target the founders committed to publicly.
5. HIRING — every currently open role you can find and its department, with special attention to
   go-to-market roles (SDR, account executive, product marketing, events marketing, solutions
   consultant, head of sales). Quote the parts of GTM job descriptions that describe HOW they plan
   to find and reach target customers (target lists, account research, outbound, cold email,
   territory/patch planning). Note who each role reports to.
6. GO-TO-MARKET MOTION & TOOLING — how they acquire customers today (founder-led? outbound?
   events? partners? private-equity roll-up relationships?), and what sales/marketing tooling is
   visible or conspicuously absent (CRM, sales engagement, ABM/intent platforms, data providers).
7. LEADERSHIP & GTM ORG — every named executive and GTM leader with their exact title and the
   source naming them, including the CRO and any director-level growth/sales leaders, and when
   each joined. Note any leadership seat that is currently VACANT or being recruited.
8. OPERATIONAL PAIN & STRATEGIC MOVES — the constraints the company itself describes, and the
   moves it is making next.
9. CULTURE & RESONANCE — how the company and its founders talk about themselves and their work;
   any publicly aired frustration, employee sentiment or attrition signal.
10. TIMING EVENTS, newest first, each dated — anything in the last 6 months that changes the
    company's buying posture.
"""


# -- the product-catalog system prompt, written to §3's "request discipline" bullet -------------

PRODUCT_CATALOG_SYSTEM = """You are cataloguing every distinct offering a single company sells.

TARGET LOCK — the ONLY subject is Zafran Security, domain zafran.io, an AI-native
threat-exposure-management cybersecurity company. "Zafran" is also a saffron/spice brand and the
name of several restaurants; none of those are the subject.

RULES
  * Prefer pages on the company's own domain.
  * List every distinct product page you can find. Do not merge two offerings into one entry.
  * Keep integrations and partner programs separate from standalone products.
  * Never invent an offering. If you are unsure of a field, omit that field.
  * Use the offering's official name exactly as the company writes it.
"""

PRODUCT_CATALOG_CHARTER = (
    "List every product, platform, integration, partner program and service that Zafran Security "
    "(zafran.io) sells or offers, as published on its own website. For each one give its official "
    "name, a one-or-two-sentence portfolio-level description, its offering kind, its product "
    "family if it has one, its lifecycle stage, and the canonical page on zafran.io. In "
    "coverage_note, say what you searched and what may still be missing."
)


def _ledger_rows(path: Path, row_id: str) -> dict[str, object]:
    """The one ledger row a result cites, read back off disk."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    matches = [row for row in rows if row["row_id"] == row_id]
    assert len(matches) == 1, f"expected exactly one ledger row {row_id}, found {len(matches)}"
    return matches[0]  # type: ignore[no-any-return]


def _assert_metered(cost: CallCost, root: Path) -> None:
    """A paid call reports a real cost, and the result value's ``cost`` *is* the ledger row.

    Every Exa return value carries this, so the helper takes the :class:`CallCost` rather than a
    loose pair of fields: if the two ever disagreed, the number a caller reports and the number
    the money trail holds would have drifted apart, which is the failure this shape prevents.
    """
    assert cost.cost_source == "metered", "Exa meters every call it serves"
    assert cost.cost_usd is not None and cost.cost_usd > 0, "Exa reported no cost for a paid call"
    row = _ledger_rows(root / "ledger.jsonl", cost.ledger_row_id)
    assert row["phase"] == "result"
    assert Decimal(str(row["cost_usd"])) == cost.cost_usd
    assert row["provider"] == cost.provider == "exa"
    assert row["extras"]["cost_source"] == "metered"
    assert row["raw_ref"] == cost.raw_ref
    assert "cost_breakdown" in row["extras"], "the costDollars breakdown is kept on the row"


def _client(
    make_caller: Callable[..., ProviderCaller], live_secrets: Secrets
) -> tuple[ExaClient, ProviderCaller]:
    key = require_secret(live_secrets, "exa_api_key")
    caller = make_caller()
    return ExaClient(caller, SecretStr(key)), caller


def _write_artifact(root: Path, name: str, text: str) -> Path:
    """Keep the paid-for answer on disk (Constraint 4) so a reviewer can read what was bought."""
    directory = root / "exa"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


# -- search ------------------------------------------------------------------------------------


def test_a_domain_restricted_search_returns_only_those_domains(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path, live_secrets: Secrets
) -> None:
    """``includeDomains`` is a hard filter: if it leaks, every scoped sweep in the lane is wrong."""
    client, _ = _client(make_caller, live_secrets)

    result = client.search(
        '"Zafran Security" ABM manager job',
        include_domains=JOB_BOARD_DOMAINS,
        label="live-zafran-jobs",
    )

    assert result.status == 200
    assert result.results, "the job-board sweep returned nothing at all"
    for hit in result.results:
        assert hit.url is not None
        assert any(domain in hit.url for domain in JOB_BOARD_DOMAINS), hit.url
    _assert_metered(result.cost, arv2_raw_root)
    assert result.request_id is not None
    assert result.raw_ref is not None and Path(result.raw_ref).exists()
    # The pre-existing fields are kept for compatibility and must not drift from `cost`.
    assert (result.cost_usd, result.raw_ref, result.ledger_row_id) == (
        result.cost.cost_usd,
        result.cost.raw_ref,
        result.cost.ledger_row_id,
    )


def test_a_date_bounded_search_returns_results_carrying_their_published_date(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path, live_secrets: Secrets
) -> None:
    """A date bound is only useful if the rows come back dated — the mapper must keep it."""
    client, _ = _client(make_caller, live_secrets)

    result = client.search(
        '"Zafran Security" funding',
        start_published_date="2025-01-01",
        label="live-zafran-funding",
    )

    assert result.status == 200
    assert result.results
    dated = [hit for hit in result.results if hit.published_date]
    assert dated, "every result came back without a publishedDate"
    assert all(hit.published_date >= "2025-01-01" for hit in dated)  # type: ignore[operator]
    _assert_metered(result.cost, arv2_raw_root)


# -- contents ----------------------------------------------------------------------------------


def test_contents_returns_indexed_text_for_a_site_and_a_video(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path, live_secrets: Secrets
) -> None:
    """No ``livecrawl``: this is the indexed copy, and it must still carry text for both URLs."""
    client, _ = _client(make_caller, live_secrets)

    result = client.contents(CONTENTS_URLS, label="live-contents")

    assert result.status == 200
    assert len(result.results) == len(CONTENTS_URLS)
    for hit in result.results:
        assert hit.text, f"no text returned for {hit.url}"
    assert result.statuses, "per-URL statuses were not surfaced"
    assert {status.status for status in result.statuses} == {"success"}
    _assert_metered(result.cost, arv2_raw_root)


# -- deep reasoning ----------------------------------------------------------------------------


def test_the_zafran_dossier_comes_back_cited_and_admits_what_it_could_not_find(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path, live_secrets: Secrets
) -> None:
    """The paid-for artefact: a real dossier, and honest NOT FOUND markers rather than guesses.

    ``NOT FOUND`` is the load-bearing assertion. A model that fabricates rather than admits a gap
    produces a *longer* report, so length alone would grade a confabulation as a success.
    """
    client, _ = _client(make_caller, live_secrets)

    result = client.deep_reasoning(
        system_prompt=ZAFRAN_SYSTEM,
        query=ZAFRAN_CHARTER,
        output_schema=report_output_schema(),
        highlights_query=ZAFRAN_HIGHLIGHTS_QUERY,
        label="live-deep-zafran",
    )

    assert result.status == 200
    assert result.report_text is not None
    path = _write_artifact(arv2_raw_root, "deep_zafran.md", result.report_text)
    assert len(result.report_text) >= 3000, f"thin dossier ({len(result.report_text)}) at {path}"
    assert "NOT FOUND" in result.report_text
    assert result.results, "the dossier cited no sources at all"
    _assert_metered(result.cost, arv2_raw_root)


def test_the_probook_dossier_comes_back_cited_and_disambiguated(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path, live_secrets: Secrets
) -> None:
    """A second account with a hostile name collision (HP ProBook laptops) tests the lock."""
    client, _ = _client(make_caller, live_secrets)

    result = client.deep_reasoning(
        system_prompt=PROBOOK_SYSTEM,
        query=PROBOOK_CHARTER,
        output_schema=report_output_schema(),
        label="live-deep-probook",
    )

    assert result.status == 200
    assert result.report_text is not None
    path = _write_artifact(arv2_raw_root, "deep_probook.md", result.report_text)
    assert len(result.report_text) >= 3000, f"thin dossier ({len(result.report_text)}) at {path}"
    assert "NOT FOUND" in result.report_text
    _assert_metered(result.cost, arv2_raw_root)


def test_the_product_catalog_schema_is_accepted_and_returns_typed_offerings(
    make_caller: Callable[..., ProviderCaller], arv2_raw_root: Path, live_secrets: Secrets
) -> None:
    """``ARV2-PRODUCT-CATALOG-CONTRACT.md`` §3 against the real API, ``enum`` included.

    §3 anticipates that Exa may reject ``enum``. If it does, this test fails loudly with the
    provider's own words and the raw record path — the schema is the contract and is not quietly
    edited to make a test pass.
    """
    client, _ = _client(make_caller, live_secrets)

    result = client.deep_reasoning(
        system_prompt=PRODUCT_CATALOG_SYSTEM,
        query=PRODUCT_CATALOG_CHARTER,
        output_schema=product_catalog_output_schema(),
        include_domains=["zafran.io"],
        num_results=40,
        label="live-product-catalog-zafran",
    )

    assert result.status == 200, f"Exa refused the §3 schema: {result.output_text[:800]}"
    catalog = result.output_object
    _write_artifact(
        arv2_raw_root, "product_catalog_zafran.json", json.dumps(catalog, indent=2, default=str)
    )
    assert isinstance(catalog, dict), f"no structured output; raw at {result.raw_ref}"
    products = catalog.get("products")
    assert isinstance(products, list) and products, f"empty catalog; raw at {result.raw_ref}"
    for product in products:
        assert isinstance(product, dict)
        assert product.get("name")
        assert product.get("offering_kind")
    assert result.grounding is not None, "§3 expects per-field citations in output.grounding"
    _assert_metered(result.cost, arv2_raw_root)
