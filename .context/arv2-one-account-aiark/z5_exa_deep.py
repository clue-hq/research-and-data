"""Z5 — ONE Exa deep-reasoning account call for Zafran Security.

Wire facts (do not rediscover): type="deep-reasoning"; outputSchema must carry exactly ONE
string property; contents.text + highlights; numResults 20; ~40s; retry the silent-fail
signature (<=9 results / ~$0.015) once.
"""
import json, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

LOCK = """  Zafran Security (zafran.io), legal name "Zafran Security Ltd.", an AI-native
  threat-exposure-management cybersecurity company founded 2022 by Sanaz Yashar (CEO),
  Ben Seri (CTO) and Snir Havdala (CPO, since departed), HQ New York City with R&D in Tel Aviv,
  ~167 employees, $130.5M raised across 4 rounds, $60M Series C led by Menlo Ventures announced
  2025-12-02, plus a Cisco Investments strategic investment announced 2026-07-22.

EXCLUDE and name any same-name entity: "Zafran" is also a saffron/spice brand and the name of
several restaurants and food companies; there is also "Zafran Global". NONE of those are the
subject."""

SYSTEM = f"""You are a B2B account researcher producing an evidence-grounded dossier on ONE company
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

ALREADY_KNOWN = """ALREADY ESTABLISHED (do NOT spend the budget re-deriving these; treat as given and
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

CHARTER = f"""Produce an exhaustive, cited markdown dossier on Zafran Security (zafran.io) covering:

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

t0 = time.time()


def run(label):
    return C.exa({
        "query": CHARTER, "type": "deep-reasoning", "systemPrompt": SYSTEM,
        "numResults": 20, "stream": False,
        "contents": {"text": {"maxCharacters": 10000},
                     "highlights": {"query": "Zafran Security go-to-market marketing leadership "
                                             "hiring funding customers Cisco acquisition rumour",
                                    "maxCharacters": 2000}},
        "outputSchema": {"type": "object", "required": ["report"], "additionalProperties": False,
                         "properties": {"report": {
                             "type": "string",
                             "description": "The exhaustive cited markdown dossier answering every "
                             "numbered section of the charter, with a verbatim quote and URL "
                             "behind every assertion and explicit NOT FOUND markers."}}},
    }, label=label, timeout=1200, est_usd=0.05)


resp = run("z5_deep_zafran")
text = C.deep_report_text(resp)
cost = (resp.get("costDollars") or {}).get("total") or 0
n = len(resp.get("results") or [])
if len(text) < 3000 or (n <= 9 and cost <= 0.016):
    print(f"  SILENT-FAIL SIGNATURE (n={n}, cost={cost}, chars={len(text)}) -> one retry")
    resp = run("z5_deep_zafran_retry")
    t2 = C.deep_report_text(resp)
    if len(t2) > len(text):
        text = t2
open("report_account_zafran_deep.md", "w").write(text)
el = time.time() - t0
C.timing_record("Z5_exa_deep", el, "one deep-reasoning call")
json.dump({"chars": len(text), "not_found": text.count("NOT FOUND"),
           "elapsed_s": round(el, 1), "n_results": len(resp.get("results") or []),
           "cost_usd": (resp.get("costDollars") or {}).get("total"),
           "http": resp.get("_http_status")}, open("z5_deep_summary.json", "w"), indent=2)
print(f"\nZ5 {round(el,1)}s chars={len(text)} NOT_FOUND={text.count('NOT FOUND')} "
      f"spend={C.total_spend()}")
