"""B1b — ONE Exa deep-reasoning call per account (5 calls), each target-locked.

Wire facts (do not rediscover): type="deep-reasoning" (NOT `deep`); outputSchema must carry
exactly ONE string property or Exa returns no output; contents.text + highlights; numResults 20-25;
stream false. Charter absorbs what would otherwise be separate gap-fills.
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

LOCK = {
    "zafran": """  Zafran Security (zafran.io), an AI-native threat-exposure-management cybersecurity
  company, founded 2022 by Snir Havdala and Sanaz Yashar, offices in New York City and Tel Aviv,
  ~$130M raised, $60M Series C led by Menlo Ventures announced 2025-12-02, plus a Cisco
  Investments strategic investment announced 2026-07-22.

EXCLUDE and name any same-name entity: "Zafran" is also a saffron/spice brand and the name of
several restaurants and food companies; there is also "Zafran Global". NONE of those are the
subject.""",
    "cogent": """  Cogent Security, Inc. (cogent.com), a San Francisco AI-vulnerability-management
  cybersecurity company founded 2024, ~49 employees, which raised a $42M Series A led by Bain
  Capital Ventures with Greylock and Definition, announced 2026-02-18.

EXCLUDE and explicitly name any same-name entity — this is the highest same-name risk in the run:
"Cogent Communications Holdings" (NASDAQ: CCOI, cogentco.com, the internet/backbone carrier),
"Cogent Systems"/"Cogent Inc" (fingerprint biometrics, acquired by 3M), "Cogent Infotech",
"Cogent Labs", "Cogent Analytics", "Cogent Bank". NONE of those are the subject. If a source is
about an ISP, a bank, a biometrics vendor or an IT staffing firm, say so and discard it.""",
    "harmonic": """  Harmonic Security, Inc. (harmonic.security), an AI-data-security / AI-governance
  company founded 2023 by Alastair Paterson and Bryan Woolgar-O'Neil, US + UK workforce,
  $17.5M Series A, investors include Ten Eleven Ventures, N47/Storm Ventures and In-Q-Tel.

EXCLUDE and name any same-name entity: "Harmonic Inc." (NASDAQ: HLIT, video-delivery /
broadband hardware), "Harmonic" the a16z-backed mathematical-superintelligence company
(harmonic.fun, Aristotle), "Harmonic Discovery", "Harmonic Bionics", "Harmonic Drive".
NONE of those are the subject.""",
    "vendelux": """  Vendelux (vendelux.com), a New York City B2B event-intelligence software company
  founded 2021 by Kyle Fitzgerald (CEO), which raised a $50M Series B led by Tribeca Venture
  Partners announced 2026-07-08 (FirstMark led the Series A); ~$66.4M total raised.

EXCLUDE any same-name entity you encounter and say so.""",
    "uptiq": """  UPTIQ, Inc. (uptiq.ai), a Dallas, Texas company founded 2022 selling AI agents to
  banks, credit unions, lenders and wealth-management firms; CEO Snehal Fulzele; ~129 employees;
  $25M Series B announced 2026-02-12/13; $55M total equity; "150+ Financial Institutions Trust Us".

EXCLUDE and name any same-name entity: "Uptick", "Uptiq Wealth" if unrelated, and any
similarly-spelled fintech. NONE of those are the subject unless they are literally uptiq.ai.""",
}

EXTRA = {
    "zafran": """
SPECIAL PROBE (highest value in this run): Zafran published a req "Senior Manager, ABM &
Integrated Campaigns" (USA, Marketing) on 2026-06-17 that is STILL LISTED on their Ashby board on
2026-08-31 — 75 days open. Find (a) who the "Head of Growth Marketing" it reports to actually IS,
by name, with a source; (b) every other marketing person at Zafran by name and title; (c) any
evidence they use 6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze, Influ2, Madison Logic,
Clay, Common Room or any ABM/intent platform — quote it if found, and write NOT FOUND if not;
(d) whether the marketing organisation sits in the USA or in Tel Aviv; (e) the actual ARR number
behind "Zafran Triples ARR".""",
    "cogent": """
SPECIAL PROBE: Cogent's Ashby board on 2026-08-31 lists TEN GTM/marketing reqs including
"Head of Demand Generation" (New York, published 2026-08-14) and "Field Marketing Manager"
(New York, published 2026-08-21). Find (a) who the "Head of Growth" that the Head of Demand
Generation reports to actually IS, by name; (b) every named marketing/GTM leader at Cogent;
(c) the CEO and founders by name; (d) any ABM/intent tooling evidence — quote or NOT FOUND;
(e) any customer names, logo count, ARR or pipeline number they have published.""",
    "harmonic": """
SPECIAL PROBE (a negative result matters as much as a positive one): Harmonic previously
advertised a req "Account-Based Marketing Manager, Strategic Accounts" (New York, $93K-$108K).
On 2026-08-31 that requisition id resolves to "Business Development Representative - East"
instead, and no ABM role appears on their 5-job board. Find out (a) whether an ABM manager was
HIRED — search for anyone at Harmonic Security with an ABM / account-based-marketing /
campaign-manager title and NAME them with a source; (b) who runs marketing at Harmonic (CMO /
VP Marketing / Head of Corporate Marketing) by name; (c) any real ARR / customer-count / logo
evidence (a LinkedIn "$1M annual revenue" estimate is NOT evidence — say NOT FOUND if that is all
there is); (d) what the In-Q-Tel investment implies about their target buyers; (e) any ABM/intent
tooling evidence — quote or NOT FOUND.""",
    "vendelux": """
SPECIAL PROBE (do this FIRST — it can disqualify the account): Vendelux sells event intelligence
to B2B marketers, which is adjacent to the buyer of an ABM platform. Determine from their Series B
coverage and their own site whether their roadmap is moving into (i) campaign execution,
(ii) account intelligence / intent data, or (iii) outbound orchestration — quote the roadmap
language verbatim. Then: (a) who runs marketing at Vendelux TODAY, by name and title — note they
posted a "Head of Growth Marketing" req on 2026-08-27, four days ago; (b) whether there is a
CMO/VP Marketing above that seat; (c) why an "Outreach Campaign Operations Manager" req
(published 2026-04-21, still open 132 days later) sits in the CUSTOMER SUCCESS department rather
than Marketing; (d) any ABM/intent tooling they use — quote or NOT FOUND; (e) named customers,
ARR, or customer counts.""",
    "uptiq": """
SPECIAL PROBE: Uptiq's own careers page on 2026-08-31 lists only THREE open roles, all in India
(Site Reliability Engineer, Technical Support Engineer, SBA Loan Specialist) — zero US
go-to-market or marketing reqs. Find (a) who owns marketing at Uptiq, by name and title —
CMO / VP Marketing / Head of Marketing / Head of Growth; if nobody holds that title, say so
explicitly; (b) everything the GrowthSpree ABM case study actually says — what program was run,
over how many accounts, for how long, what the $400K+ pipeline number covers, and whether the
engagement is still live; (c) any evidence of ABM/intent tooling; (d) their published customer
count and any ARR number; (e) the exact remaining addressable universe (they say 150+ financial
institutions; how many US banks and credit unions exist).""",
}

SYSTEM_TMPL = """You are a B2B account researcher producing an evidence-grounded dossier on ONE company
for a go-to-market team. Today's date is 2026-08-31.

TARGET LOCK — the ONLY subject is:
{lock}

RULES
  * Every factual assertion carries a VERBATIM quote and the URL it came from.
  * If you cannot find something, write "NOT FOUND" for it. Never estimate, never infer a number,
    never fill a gap with a plausible guess. An honest NOT FOUND is a correct answer.
  * Distinguish what the company claims about itself from what a third party reports.
  * A LinkedIn/Tracxn/CB-Insights auto-estimate is an ESTIMATE — label it as one, never as fact.
  * Prefer primary sources: the company's own pages, its job postings, the funding wire release,
    the investors' announcement posts, the founders' own writing and posts.
  * Name every person with their exact title and the URL that names them. Never invent a person.
"""

CHARTER_TMPL = """Produce an exhaustive, cited markdown dossier on {name} ({domain}) covering:

1. IDENTITY & DISAMBIGUATION — legal/operating name, HQ address (and where the GO-TO-MARKET team
   actually sits, if different), founding year, domain(s), company LinkedIn URL, employee count
   with its source, and an explicit list of the same-name entities you excluded and why.
2. PRODUCT & WHO THEY SELL TO — what the product does in their own words, the exact buyer title
   they sell to, the size and enumerability of their target universe (quote any number of possible
   customers), pricing model if published.
3. TRACTION — named customers, logo counts, ARR/revenue if stated, per-customer outcome metrics,
   and WHO claimed each number (company vs investor vs press vs an automated estimate).
4. FUNDING — every round with exact amount, date, lead investor and participants; total raised;
   any stated use of proceeds or growth commitment made publicly.
5. GO-TO-MARKET HIRING — every open go-to-market / marketing / sales role you can find, with its
   published date and whether it is still open. Quote the parts of the job descriptions that
   describe HOW they find and reach target accounts (target account lists, account research,
   outbound, campaigns, ABM, field marketing, events). Note who each role reports to. Flag any
   role that has been open a long time.
6. MARKETING & ABM TOOLING — what marketing/sales tooling is visible or conspicuously absent:
   CRM, marketing automation, sales engagement, and specifically ABM/intent platforms
   (6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze, Influ2, Madison Logic, ZoomInfo,
   Clay, Common Room). Quote any evidence. Write NOT FOUND rather than guessing.
7. LEADERSHIP & GTM ORG — every named executive and marketing/growth leader with exact title and
   the source that names them, plus when they joined. Explicitly note any GTM seat that is VACANT
   or being recruited, and any recent GTM leadership hire (<12 months).
8. OPERATIONAL PAIN & STRATEGIC MOVES — the constraints the company itself describes, and the
   moves it says it is making next.
9. CULTURE & RESONANCE — how the company and its leaders talk about themselves; any publicly aired
   frustration, employee-sentiment or attrition signal; any award or recognition.
10. TIMING EVENTS, newest first, each dated — anything in the last 6 months that changes the
    company's buying posture.
{extra}
"""

ACCTS = {
    "zafran": ("Zafran Security", "zafran.io"),
    "cogent": ("Cogent Security, Inc.", "cogent.com"),
    "harmonic": ("Harmonic Security, Inc.", "harmonic.security"),
    "vendelux": ("Vendelux", "vendelux.com"),
    "uptiq": ("UPTIQ, Inc.", "uptiq.ai"),
}

only = sys.argv[1:] or list(ACCTS)
t_all = time.time()
summary = {}

for key in only:
    name, domain = ACCTS[key]
    t0 = time.time()
    resp = C.exa(
        {
            "query": CHARTER_TMPL.format(name=name, domain=domain, extra=EXTRA[key]),
            "type": "deep-reasoning",
            "systemPrompt": SYSTEM_TMPL.format(lock=LOCK[key]),
            "numResults": 22,
            "stream": False,
            "contents": {
                "text": {"maxCharacters": 10000},
                "highlights": {
                    "query": f"{name} go-to-market marketing leadership hiring funding customers",
                    "maxCharacters": 2000,
                },
            },
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
        label=f"b1b_deep_{key}",
        timeout=900,
        est_usd=0.05,
    )
    text = C.deep_report_text(resp)
    open(f"report_account_{key}.md", "w").write(text)
    el = time.time() - t0
    C.timing_record(f"B1b_deep_{key}", el, "exa deep-reasoning, 1 call")
    summary[key] = {
        "chars": len(text),
        "not_found": text.count("NOT FOUND"),
        "elapsed_s": round(el, 1),
        "cost_usd": (resp.get("costDollars") or {}).get("total"),
        "http": resp.get("_http_status"),
    }
    print(f"  -> {key}: {len(text)} chars, {text.count('NOT FOUND')} NOT FOUND, {round(el,1)}s")
    time.sleep(1.2)

json.dump(summary, open("b1b_deep_summary.json", "w"), indent=2)
C.timing_record("B1b_TOTAL", time.time() - t_all, f"{len(only)} deep-reasoning calls")
print(f"\nPHASE B1b {round(time.time()-t_all,1)}s spend={C.total_spend()} credits={C.total_credits()}")
