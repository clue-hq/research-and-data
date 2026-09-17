"""Step 3 — THE account deep call. Exactly ONE Exa `deep-reasoning` request, NO outputSchema.

Free-form, citation-dense report so a cheap model can structure it afterwards (the whole point of
this run's cost architecture: maximum information per expensive call).
"""

from clue_lib import exa, exa_output_text, save_raw, total_spend

SYS = """You are a senior B2B account researcher producing a decision-grade dossier on ONE exact
company for a sales team that sells an AI account-based-marketing platform.

THE EXACT TARGET, and nothing else:
  Company: Lassie
  Domain: www.lassie.ai (the marketing site also resolves at getlassie.com)
  LinkedIn: linkedin.com/company/lassie
  What it is: a San Francisco AI startup building "AI that runs the doctor's office" - automating
  administrative and insurance/billing workflows for independent dental and medical practices.
  Founders: Steijn Pelle and Frederic (Frederik) Renken. Raised a $35M Series A led by Andreessen
  Horowitz, announced 3 June 2026.

DISAMBIGUATION - THIS IS CRITICAL. Several unrelated entities share the name "Lassie":
  - Lassie (lassie.co / lassie.se), a Swedish/European PET INSURANCE company - NOT the target.
  - Lassie, the fictional collie / the film and TV franchise - NOT the target.
  - Any veterinary, pet-care, or dog-related "Lassie" - NOT the target.
If a source is about pet insurance, pets, dogs, or the TV collie, DISCARD it and say so. Only use
sources that are unambiguously about the SF dental/healthcare-admin AI company at lassie.ai.

Ground EVERY fact in a public page. For every fact give: the fact, a VERBATIM QUOTE copied exactly
from the source, and the SOURCE URL. If a fact cannot be found on a public page, write
"NOT FOUND" - never guess, never infer a number, never fill a gap with a plausible-sounding claim.
Prefer primary sources (lassie.ai pages, the company's own job postings on jobs.ashbyhq.com/lassie,
the a16z announcement, the BusinessWire release, founder posts) over aggregators.

Write a long, dense, well-organised markdown report with these numbered sections. Do not skip a
section; if a section has nothing, write the heading and "NOT FOUND".

1. IDENTITY AND DISAMBIGUATION - legal/operating name, HQ, founding year, what it actually sells,
   in one paragraph; then an explicit list of same-name entities you EXCLUDED and why.
2. PRODUCT AND TARGET VERTICAL - exactly what the product does, which practice types it serves
   (dental? medical? veterinary?), which workflows it automates (claims, EOB, insurance
   verification, phone, scheduling), pricing if public, integrations/PMS or EHR systems named.
   Quote the product pages.
3. CUSTOMERS AND TRACTION - number of practices/dentists served, named customers, ARR or revenue
   claims, growth claims, testimonials. Quote each.
4. FUNDING HISTORY - every round with date, amount, stage, lead investor, participating investors,
   and the announcement URL. Include any seed/pre-seed round before the Series A.
5. TEAM AND GTM COMPOSITION - total headcount, engineering vs sales vs marketing split, and
   specifically: do they have ANY dedicated salespeople, marketers or SDRs today? Name every
   employee you can find with their title (LinkedIn, team page, job postings, press).
6. GO-TO-MARKET MOTION - hard evidence of HOW they acquire customers: founder-led selling,
   in-person events/study clubs, referrals, outbound email/cold calling, paid ads, direct mail,
   conferences/trade shows, partnerships with DSOs or dental service organizations. Quote the
   evidence. Also: any public evidence of the sales/marketing TOOLS they use (CRM, outbound
   tooling, ad platforms).
7. HIRING SIGNALS - every open role you can find, especially go-to-market roles (growth, GTM,
   account executive, SDR, marketing). For each: exact title, location, posting URL, and a
   verbatim quote from the job description describing the go-to-market work. Note salary bands
   if published.
8. LEADERSHIP AND KEY PEOPLE - the founders and any executives/leads, with exact titles, prior
   companies, and a source URL each. Flag who appears to own revenue/growth.
9. OPERATIONAL PAIN AND STRATEGIC MOVES - what problems the company itself is publicly wrestling
   with (scaling sales into a fragmented SMB market, hiring, distribution), and its stated
   strategy/roadmap (new verticals beyond dental, new products). Quote statements from founders
   or investors.
10. CULTURE AND RESONANCE - how the company writes and talks about itself: values, tone, working
    style, what founders say publicly, employee sentiment if any exists, any publicly aired
    frustrations. Quote the exact language.
11. TIMING SIGNALS - dated events in the last ~18 months (funding, launches, hires, expansions,
    press) with dates and URLs, newest first.
12. SOURCE LIST - every URL you used, one per line, each marked [primary] or [secondary].
"""

QUERY = (
    "Lassie lassie.ai San Francisco AI startup for dental practices and doctors' offices: "
    "$35M Series A Andreessen Horowitz, founders Steijn Pelle and Frederic Renken, product for "
    "dental insurance claims and EOB automation, customers, headcount, go-to-market motion, "
    "open sales growth and GTM jobs, company values and culture"
)

resp = exa(
    {
        "query": QUERY,
        "type": "deep-reasoning",
        "numResults": 25,
        "systemPrompt": SYS,
        "contents": {
            "text": {"maxCharacters": 10000},
            "highlights": {
                "query": "Lassie dental AI funding team hiring go-to-market customers",
                "maxCharacters": 2000,
            },
        },
        "stream": False,
    },
    label="account_deep_lassie",
    timeout=900,
)

report = exa_output_text(resp)
save_raw("account_deep_report_text", {"chars": len(report), "report": report})
open("account_report.md", "w").write(report)
print("\n---- report chars:", len(report))
print("cost:", (resp.get("costDollars") or {}).get("total"), "total spend $", total_spend())
print(report[:3000])
