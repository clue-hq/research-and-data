"""Step 6 — ONE Exa `deep-reasoning` call on the account.

v2's paid-for mechanics, reused exactly:
  * type=deep-reasoning (NOT `deep` — the lite variant asserted a stale headcount v2's reasoning
    variant refused);
  * a SINGLE free-form string property in outputSchema (no schema at all -> NO output key);
  * the charter absorbs what v2 had to buy as separate gap-fills (funding history, hiring board,
    customers, tooling), per v2 §8.7 improvement #2.
"""

import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

SYSTEM = """You are a B2B account researcher producing an evidence-grounded dossier on ONE company.

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

CHARTER = """Produce an exhaustive, cited markdown dossier on Probook (probook.ai) covering:

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

resp = C.exa(
    {
        "query": CHARTER,
        "type": "deep-reasoning",
        "systemPrompt": SYSTEM,
        "outputSchema": {
            "type": "object",
            "required": ["report"],
            "additionalProperties": False,
            "properties": {
                "report": {
                    "type": "string",
                    "description": "The exhaustive cited markdown dossier answering every "
                    "numbered section of the charter, with a verbatim quote and URL behind "
                    "every assertion and explicit NOT FOUND markers.",
                }
            },
        },
    },
    label="account_deep",
    timeout=900,
)

text = C.exa_output_text(resp)
if text.strip().startswith("{"):
    import json

    try:
        obj = json.loads(text)
        r = obj.get("report")
        text = r.get("value") if isinstance(r, dict) else (r or text)
    except Exception:
        pass
open("account_report.md", "w").write(text)
print(f"report chars: {len(text)}  NOT FOUND markers: {text.count('NOT FOUND')}")
print("TOTAL:", C.total_spend())
