"""H5 — the ONE Exa deep-reasoning account call for Hotel Equities.

Wire facts (proven on the Zafran run, do not rediscover): type="deep-reasoning"; outputSchema
carries exactly ONE string property `report`; contents.text 10k + highlights; numResults 20-25;
stream false; ~40s-several minutes; retry once on the silent-fail signature (<=9 results and
~$0.015 cost).

The charter is written for CONDUIT's fit: Conduit sells an AI agent platform for hospitality
operations (guest messaging + voice, PMS write-back incl. a June 2026 two-way Oracle OPERA
integration, brand-over-property configuration, per-unit pricing). So the questions that matter
are the PMS/brand-mandate picture, guest-messaging tools in use, after-hours guest response,
labor pressure at the front desk, merger-integration timing, and the executives' own words about
technology and consistency at scale.
"""
import json
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

LOCK = """  Hotel Equities (legal name "Hotel Equities Group, LLC"), hotelequities.com, headquartered
  in Atlanta / Alpharetta, Georgia, USA. A hotel MANAGEMENT and development company (a third-party
  operator, not an owner-REIT and not a brand): it operates roughly 300 hotels, resorts and outdoor
  destinations across the United States, Canada, the Caribbean and Latin America, spanning branded
  properties (Marriott, Hilton, IHG, Choice), independents, resorts and outdoor lodging
  ("Postcard Cabins"). It runs three divisions: Full Service, Focused Service and Lifestyle. It
  merged with Springboard Hospitality (Honolulu) in 2025. Its CEO is Ben Rafter; its COO is
  Albert ("Al") Smith, appointed July 2025; founder Fred Cerrone retired effective 2025-11-22; and
  Brad Rahinsky, the former President & CEO, is now Co-Chairman.

EXCLUDE and explicitly name any same-name entity. "Hotel Equities" is also a generic phrase in
real-estate writing ("hotel equities" as an asset class). There are unrelated companies called
Equity Hotels, Hospitality Equities, HEI Hotels & Resorts, and Equity Lifestyle Properties. NONE
of those are the subject. Lock every fact to hotelequities.com and Atlanta/Alpharetta, Georgia."""

SYSTEM = f"""You are a B2B account researcher producing an evidence-grounded dossier on ONE company
for a go-to-market team. Today's date is 2026-09-22.

TARGET LOCK — the ONLY subject is:
{LOCK}

RULES
  * Every factual assertion carries a VERBATIM quote and the URL it came from.
  * If you cannot find something, write "NOT FOUND". Never estimate, never infer a number, never
    fill a gap with a plausible guess. An honest NOT FOUND is a correct answer.
  * Distinguish what the company claims about itself from what a third party reports.
  * A LinkedIn / Crunchbase / ZoomInfo auto-estimate is an ESTIMATE — label it as one, never fact.
  * Prefer primary sources: hotelequities.com pages and blog posts, its press releases, the
    hotel-trade press (Hotel Business, Hotel Management, HOTELSMag, Hospitality Net, LODGING,
    Hotel Executive, Skift, PhocusWire, CoStar/Hotel News Now), the brands' own announcements,
    and the executives' own writing, interviews and podcast appearances.
  * Name every person with their EXACT title and the URL that names them. Never invent a person.
  * For a technology question, only assert a tool is in use if a source says so; "the brand
    mandates X for its franchised properties" is a different, weaker claim than "Hotel Equities
    uses X" — say which one you have."""

CHARTER = """Produce an exhaustive, cited markdown dossier on Hotel Equities (hotelequities.com),
organised under EXACTLY these numbered headings:

1. WHAT THEY ACTUALLY MANAGE. The portfolio: how many hotels/resorts/outdoor destinations, how
   many rooms/keys, broken down as precisely as the sources allow by division (Full Service,
   Focused Service, Lifestyle), by brand family (Marriott, Hilton, IHG, Choice, Hyatt, independent,
   Postcard Cabins), and by region (US, Canada, Caribbean, Latin America). State explicitly which
   properties they OWN versus MANAGE FOR THIRD-PARTY OWNERS, and what share of the portfolio is
   third-party managed. Quote the numbers.

2. OWNERSHIP AND CAPITAL. Who owns Hotel Equities itself; any private-equity or family-office
   backing; any capital partners, joint ventures or investment arms (e.g. an HE-branded
   development or capital vehicle); disclosed revenue or AUM; acquisitions they have made.

3. THE SPRINGBOARD HOSPITALITY MERGER (2025). Why it happened in each side's own words, what
   Springboard brought (it was a technology-forward Hawaii/West-Coast lifestyle operator), the
   deal date and structure, what the combined entity claims, how the integration is being
   sequenced, and what has been said about combining systems, teams or brands. Ben Rafter's own
   background (Aqua-Aston, Springboard, "a technology entrepreneur") and his stated plans.

4. TECHNOLOGY STACK — the most important section. For each, quote the evidence and say whether it
   is a Hotel Equities statement, a brand mandate, a vendor announcement, or NOT FOUND:
   (a) PROPERTY MANAGEMENT SYSTEMS by brand — Marriott (FSPMS/FOSSE/Lightspeed/Oracle OPERA Cloud),
       Hilton (OnQ/PEP), IHG (Opera Cloud/HIS/Concerto), Choice (choiceADVANTAGE), and whatever
       runs the independents and Postcard Cabins. Specifically: ANY exposure to Oracle OPERA or
       OPERA Cloud anywhere in the portfolio.
   (b) GUEST MESSAGING / TEXTING / GUEST-EXPERIENCE tools in use or trialled — Canary Technologies,
       Kipsu, Akia, Revinate, Duve, HiJiffy, Asksuite, Medallia, Zingle/Medallia Concierge,
       Quore, ALICE/Actabl, Whistle, Runtriz, or anything else. Name each one you find and each
       one you checked and could not evidence.
   (c) AI initiatives, automation statements, or "digital transformation" programmes, including
       anything Ben Rafter or any executive has said about AI in hotel operations.
   (d) The CONTACT-CENTRE / AFTER-HOURS GUEST RESPONSE model: is there a central reservations or
       guest-services call centre, an above-property support team, an outsourced answering
       service, or is every guest call and text handled at the property front desk?
   (e) Revenue management, CRM, housekeeping/work-order, and business-intelligence tools.
   (f) Who owns technology decisions: name any CIO, CTO, VP of Technology, VP of IT, or
       above-property systems leader, with the URL naming them. If the seat appears VACANT, say so
       and give the evidence.

5. LABOR AND OPERATING PRESSURE. Anything they or the trade press say about staffing the front
   desk, guest services, night audit or housekeeping; turnover; wage pressure; recruiting; the
   size of the above-property support team; and any statement about doing more with fewer people.

6. GUEST-SATISFACTION AND QUALITY KPIs. Marriott's Intent-to-Recommend (ITR) ranking — they claim
   to be Marriott's #1 franchise management company on ITR four years running: find the primary
   source and the exact wording. Any other GSS/ITR/brand-scorecard results, awards, or quality
   programmes, plus how they describe measuring service consistency across ~300 properties.

7. GROWTH: NEW OPENINGS, PIPELINE AND CONVERSIONS. Every signed, announced or opening property in
   the last 18 months and the forward pipeline, with dates — including SLS Punta del Este
   (announced as opening 2029), Postcard Cabins, and any conversions or new management contracts.
   New divisions or business lines launched.

8. LEADERSHIP, WITH DATES. Every named executive: CEO, COO, CFO, division Presidents, and every
   SVP/VP of Operations, Guest Experience, Commercial, Revenue, Sales & Marketing, People,
   Technology/IT, and Development — exact title, start date, where they came from, and the URL
   naming them. Cover the July 2025 merger appointments AND the November 2025 wave of executive
   appointments across the new divisions. Note every seat that is newly filled, recently vacated
   or currently vacant, with dates.

9. THE EXECUTIVES IN THEIR OWN WORDS. Verbatim quotes (with URL and date) from Ben Rafter, Al
   Smith, Brad Rahinsky and any divisional president, specifically about: technology and AI in
   hotels, guest experience, service consistency at scale, labor, simplicity, and how they choose
   vendors or systems. Al Smith has a blog post on simplicity driving consistent luxury service at
   scale; Ben Rafter has written in Hotel Executive on the future of hotel management — quote
   both at length, and find every podcast, webinar, conference panel or video appearance you can,
   with its URL and date, for any of them.

10. REPUTATION, INCLUDING NEGATIVES. This section is REQUIRED. Lawsuits, wage-and-hour or ADA
    claims, layoffs or WARN notices, owner or franchisee disputes, lost management contracts,
    receiverships or foreclosures at managed properties, franchise-agreement terminations,
    negative guest-review patterns, union activity, and any critical trade-press or
    employee-review commentary. For each, say who reported it, the date, and whether Hotel
    Equities responded.

11. TIMING EVENTS, newest first, each dated — anything in the last 12 months that changes their
    buying posture for an operations-technology purchase.

ALREADY ESTABLISHED (do NOT spend the budget re-deriving these; treat as given and go find what is
NOT here):
  - ~300 hotels/resorts/outdoor destinations; three divisions (Full Service, Focused Service,
    Lifestyle); Atlanta/Alpharetta GA; branded (Marriott, Hilton, IHG, Choice) + independent +
    resorts + Postcard Cabins.
  - Merged with Springboard Hospitality (Honolulu) in 2025. CEO Ben Rafter. COO Albert ("Al")
    Smith appointed July 2025. Founder Fred Cerrone retired effective 2025-11-22. Brad Rahinsky,
    former President & CEO, now Co-Chairman. A November 2025 wave of executive appointments.
  - They claim to be Marriott's #1 franchise management company on Intent-to-Recommend four years
    running, and have been named operator of SLS Punta del Este (opening 2029).
  - Their open roles are posted through ADP WorkforceNow across four public career centres; we
    already have the live requisition list, so do not spend the budget listing jobs. What we need
    from hiring is only what the TRADE PRESS or the company says about staffing pressure.
"""

t0 = time.time()


def run(label):
    return C.exa({
        "query": CHARTER, "type": "deep-reasoning", "systemPrompt": SYSTEM,
        "numResults": 25, "stream": False,
        "contents": {"text": {"maxCharacters": 10000},
                     "highlights": {"query": "Hotel Equities portfolio property management system "
                                             "guest messaging technology leadership Springboard "
                                             "merger openings labor Marriott intent to recommend",
                                    "maxCharacters": 2000}},
        "outputSchema": {"type": "object", "required": ["report"], "additionalProperties": False,
                         "properties": {"report": {
                             "type": "string",
                             "description": "The exhaustive cited markdown dossier answering every "
                             "numbered section of the charter, with a verbatim quote and URL "
                             "behind every assertion and explicit NOT FOUND markers."}}},
    }, label=label, timeout=1500, est_usd=0.06)


resp = run("h5_deep_hotelequities")
text = C.deep_report_text(resp)
cost = (resp.get("costDollars") or {}).get("total") or 0
n = len(resp.get("results") or [])
if len(text) < 3000 or (n <= 9 and cost <= 0.016):
    print(f"  SILENT-FAIL SIGNATURE (n={n}, cost={cost}, chars={len(text)}) -> one retry")
    resp = run("h5_deep_hotelequities_retry")
    t2 = C.deep_report_text(resp)
    if len(t2) > len(text):
        text = t2
open("report_account_hotelequities_deep.md", "w").write(text)
el = time.time() - t0
C.timing_record("H5_exa_deep_account", el, "one deep-reasoning call")
json.dump({"chars": len(text), "not_found": text.count("NOT FOUND"),
           "elapsed_s": round(el, 1), "n_results": len(resp.get("results") or []),
           "cost_usd": (resp.get("costDollars") or {}).get("total"),
           "http": resp.get("_http_status"),
           "result_urls": [r.get("url") for r in (resp.get("results") or [])]},
          open("h5_deep_summary.json", "w"), indent=2)
print(f"\nH5 {round(el,1)}s chars={len(text)} NOT_FOUND={text.count('NOT FOUND')} "
      f"spend={C.total_spend()}")
