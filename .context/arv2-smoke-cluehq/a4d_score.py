"""A4d — score every candidate against the icp.md rubric and emit candidates.json.

Evidence lines below are transcribed from raw/ responses (discovery_raw.json, verify_raw.json,
tiebreak_raw.json). Each awarded criterion carries source_url + a verbatim quote where one exists.
`inferred: true` halves the points, per icp.md §5.
"""

import json
import time

import clue_lib as L

t0 = time.time()

# ---------------------------------------------------------------- rubric machinery
MAX = {
    "A_Q1": 15, "A_Q2Q6": 10, "A_Q3": 5, "A_Q4": 5,
    "B_named_account": 10, "B_acv": 8, "B_outbound_language": 7,
    "C_stage": 10, "C_headcount": 5, "C_mktteam": 5,
    "D_no_abm_tool": 7, "D_leader_or_reqs": 5, "D_recent_round": 3,
    "E_channel_fit": 5,
}


def score(criteria):
    total = 0.0
    detail = {}
    for k, v in criteria.items():
        cap = MAX[k]
        pts = float(v.get("points", 0))
        pts = min(pts, cap)
        if v.get("inferred"):
            pts = pts / 2.0
        detail[k] = {
            "points_awarded": round(pts, 2),
            "max": cap,
            "inferred": bool(v.get("inferred")),
            "evidence": v.get("evidence"),
            "source_url": v.get("source_url"),
        }
        total += pts
    return round(total, 1), detail


def band(s):
    return "select" if s >= 75 else "strong_bench" if s >= 60 else "watch" if s >= 45 else "drop"


CANDIDATES = []


def add(name, domain, vertical, hq, stage, gates, criteria=None, dropped=None, notes=""):
    row = {
        "name": name, "domain": domain, "vertical": vertical, "hq": hq,
        "funding_stage": stage, "gates": gates, "notes": notes,
    }
    if dropped:
        row["disposition"] = "dropped"
        row["drop_reason"] = dropped
        row["fit_score"] = None
        row["band"] = "dropped_at_gate"
    else:
        s, d = score(criteria)
        row["disposition"] = "scored"
        row["fit_score"] = s
        row["band"] = band(s)
        row["rubric"] = d
    CANDIDATES.append(row)


# ============================================================ SCORED (passed H1+H2)

add(
    "Cogent Security, Inc.", "cogent.com", "V1 B2B SaaS — cybersecurity (AI vulnerability mgmt)",
    "San Francisco, CA, USA", "Series A — $42M (Feb 18, 2026)",
    {"H1_us": "PASS", "H2_series_a_plus": "PASS", "H3_quantifiable_pain": "PASS (Q1 + Q4)"},
    {
        "A_Q1": {"points": 15, "evidence": "Head of Demand Generation req: 'lead all pipeline-generating functions across marketing, including digital, partner, and field, and sales development' … 'start building your team across field/channel and digital/content so Cogent can scale pipeline with far more leverage'", "source_url": "https://jobs.ashbyhq.com/cogent-security/8ed749ff-cf21-47ec-815d-36af19ab389d"},
        "A_Q2Q6": {"points": 10, "evidence": "49 employees, enterprise-security buyer universe is large and enumerable (named CISO accounts); marketing org is being built from scratch under a Head of Growth", "source_url": "https://linkedin.com/company/cogentsecurity", "inferred": True},
        "A_Q3": {"points": 0, "evidence": "no founder/leader public complaint about outbound cost found in cheap discovery"},
        "A_Q4": {"points": 5, "evidence": "'Six months after launch, Cogent raises $42M led by Bain Capital Ventures to scale the first AI taskforce for vulnerability management.'", "source_url": "https://www.cogent.com/blog/cogent-security-raises-42m-series-a"},
        "B_named_account": {"points": 10, "evidence": "'AI systems for enterprise cybersecurity teams' — enterprise CISO motion; role explicitly owns 'field' and 'partner' channels", "source_url": "https://jobs.ashbyhq.com/cogent-security/8ed749ff-cf21-47ec-815d-36af19ab389d"},
        "B_acv": {"points": 8, "evidence": "enterprise vulnerability-management platforms sell at six figures; role is a senior player-coach with an FY27 demand model", "inferred": True},
        "B_outbound_language": {"points": 7, "evidence": "'owns the front end of the revenue engine: creating, converting, and scaling qualified pipeline' + owns sales development", "source_url": "https://jobs.ashbyhq.com/cogent-security/8ed749ff-cf21-47ec-815d-36af19ab389d"},
        "C_stage": {"points": 10, "evidence": "Series A, $42M, Bain Capital Ventures + Greylock + Definition, announced 2026-02-18", "source_url": "https://www.prnewswire.com/news-releases/cogent-security-raises-42m-series-a-to-arm-security-teams-with-autonomous-ai-agents-302691566.html"},
        "C_headcount": {"points": 5, "evidence": "'Cogent employs 49 people, founded in 2024. Headquartered in San Francisco, California, United States.'", "source_url": "https://linkedin.com/company/cogentsecurity"},
        "C_mktteam": {"points": 5, "evidence": "at 49 total headcount the marketing team is necessarily <10; the Head of Demand Gen is being hired to build it", "inferred": True},
        "D_no_abm_tool": {"points": 7, "evidence": "no ABM/personalization platform named anywhere in the req's tool expectations or on the site", "inferred": True},
        "D_leader_or_reqs": {"points": 5, "evidence": "Head of Growth already in seat (the req reports to them); Head of Demand Gen req published 2026-08-14", "source_url": "https://jobs.ashbyhq.com/cogent-security/8ed749ff-cf21-47ec-815d-36af19ab389d"},
        "D_recent_round": {"points": 3, "evidence": "Series A closed 2026-02-18, ~6 months ago", "source_url": "https://www.securityweek.com/cogent-security-raises-42-million-for-ai-driven-vulnerability-management/"},
        "E_channel_fit": {"points": 5, "evidence": "CISOs and security leaders are densely reachable on LinkedIn; a physical executive report on an org's own vulnerability posture is a natural direct-mail artifact", "inferred": False},
    },
    notes="Freshest money + an empty marketing org + a named GTM leader to report to. The textbook shape.",
)

add(
    "Harmonic Security, Inc.", "harmonic.security", "V1 B2B SaaS — cybersecurity (AI governance)",
    "San Francisco, CA, USA (US + UK workforce; the ABM role is New York, NY - Remote)",
    "Series A — $17.5M (Apr 2025), $25.96M total",
    {"H1_us": "PASS", "H2_series_a_plus": "PASS", "H3_quantifiable_pain": "PASS (Q1, strongest form)"},
    {
        "A_Q1": {"points": 15, "evidence": "An open req titled 'Account-Based Marketing Manager, Strategic Accounts' — department 'Go to Market Corporate Marketing', $93K–$108K + equity + bonus. This is literally the seat Clue automates.", "source_url": "https://jobs.ashbyhq.com/harmonic-security-inc/f568f331-f4ea-4328-a690-03772941f561"},
        "A_Q2Q6": {"points": 10, "evidence": "'Harmonic Security employs 56 people and has an annual revenue of $1M, founded in 2023' — a 56-person company opening a dedicated strategic-accounts ABM seat has far more target accounts than capacity", "source_url": "https://linkedin.com/company/harmonic-security"},
        "A_Q3": {"points": 0, "evidence": "none found"},
        "A_Q4": {"points": 5, "evidence": "'Harmonic Security Raises $17.5 Million Series A to Accelerate Zero-Touch Data Protection to Market' — market-expansion earmark, but Apr 2025 (>12 months old)", "source_url": "https://www.harmonic.security/resources/harmonic-security-raises-17-5-million-series-a-to-accelerate-zero-touch-data-protection-to-market", "inferred": True},
        "B_named_account": {"points": 10, "evidence": "the req is scoped to 'Strategic Accounts'; 'Security teams get full visibility and control across every AI surface' — enterprise motion, backed by In-Q-Tel and Ten Eleven Ventures", "source_url": "https://jobs.ashbyhq.com/harmonic-security-inc/f568f331-f4ea-4328-a690-03772941f561"},
        "B_acv": {"points": 8, "evidence": "enterprise AI-governance platform sold to security teams; In-Q-Tel backing implies government/large-enterprise deals", "inferred": True},
        "B_outbound_language": {"points": 7, "evidence": "a dedicated ABM function inside 'Go to Market Corporate Marketing' is by definition an account-based outbound motion", "source_url": "https://jobs.ashbyhq.com/harmonic-security-inc/f568f331-f4ea-4328-a690-03772941f561"},
        "C_stage": {"points": 10, "evidence": "'Stage Series A | Alive · Total Raised $25.96M · Last Raised $17.5M'", "source_url": "https://www.cbinsights.com/company/harmonic-security"},
        "C_headcount": {"points": 5, "evidence": "56 employees", "source_url": "https://linkedin.com/company/harmonic-security"},
        "C_mktteam": {"points": 5, "evidence": "56 total headcount ⇒ a marketing team in the low single digits", "inferred": True},
        "D_no_abm_tool": {"points": 7, "evidence": "no ABM platform named in the req; a company hiring its FIRST ABM manager is unlikely to have an enterprise ABM platform installed", "inferred": True},
        "D_leader_or_reqs": {"points": 5, "evidence": "the ABM req itself is the open GTM seat; timeline page shows continuous GTM build-out ('2026 • January — Upscaled Brand Launched')", "source_url": "https://www.harmonic.security/about"},
        "D_recent_round": {"points": 0, "evidence": "last confirmed round Apr 2025 — outside the 12-month window"},
        "E_channel_fit": {"points": 5, "evidence": "CISO/security-leader audience is LinkedIn-dense; the $93–108K band signals a budget that a platform beats on cost"},
    },
    notes="The purest possible Q1: they are hiring the exact role Clue replaces, at a modest salary band.",
)

add(
    "Vendelux", "vendelux.com", "V1-adjacent — martech (B2B event intelligence)",
    "New York, NY, USA", "Series B — $50M (Jul 2026), $66.4M total",
    {"H1_us": "PASS", "H2_series_a_plus": "PASS", "H3_quantifiable_pain": "PASS (Q4 + Q7)"},
    {
        "A_Q1": {"points": 6, "evidence": "'Outreach Campaign Operations Manager' (Customer Success, $80K–$120K) and 'Growth Marketing Lead' ($160K–$230K OTE, published 2026-04-16) — campaign assembly done by hand, but neither req is explicitly account-research-shaped", "source_url": "https://jobs.ashbyhq.com/vendelux/7dfeabd3-7595-490b-af19-dff052216d67"},
        "A_Q2Q6": {"points": 10, "evidence": "their buyer universe (B2B companies that spend on events) is large and enumerable; they are staffing it with individual hires", "inferred": True},
        "A_Q3": {"points": 0, "evidence": "none found"},
        "A_Q4": {"points": 5, "evidence": "'Vendelux, a live events information platform, has raised $50 million to help marketers capitalize on that. Tribeca Venture Partners led the company's Series B raise' (2026-07-08)", "source_url": "https://www.businessinsider.com/vendelux-just-raised-50-million-to-capitalize-live-b2b-events-2026-7"},
        "B_named_account": {"points": 8, "evidence": "sells a high-consideration platform to enterprise event/field-marketing orgs; hiring a Revenue Operations Lead ($150K–$185K) to industrialize the motion", "source_url": "https://jobs.ashbyhq.com/vendelux/b5ea116c-95dc-47ad-adb0-3cdfa97a7620", "inferred": False},
        "B_acv": {"points": 8, "evidence": "event-intelligence platforms sell to enterprise marketing budgets; $66.4M raised against a NYC cost base implies a mid-five-figure+ ACV", "inferred": True},
        "B_outbound_language": {"points": 7, "evidence": "an entire req named 'Outreach Campaign Operations Manager' — outbound is a staffed function", "source_url": "https://jobs.ashbyhq.com/vendelux/7dfeabd3-7595-490b-af19-dff052216d67"},
        "C_stage": {"points": 10, "evidence": "'Founded Year 2021 · Stage Series B | Alive · Total Raised $66.4M · Last Raised $50M | 2 mos ago'", "source_url": "https://www.cbinsights.com/company/vendelux"},
        "C_headcount": {"points": 5, "evidence": "Series B, NYC, 4+ concurrent GTM reqs — headcount consistent with the 30–300 band", "inferred": True},
        "C_mktteam": {"points": 5, "evidence": "hiring both a Growth Marketing Lead and a Product Marketing Lead ⇒ the marketing team today is small", "source_url": "https://jobs.ashbyhq.com/vendelux/634ef70b-e32c-409c-bcb1-f8ac69e8d18c", "inferred": True},
        "D_no_abm_tool": {"points": 7, "evidence": "no ABM platform detected", "inferred": True},
        "D_leader_or_reqs": {"points": 5, "evidence": "FOUR concurrent GTM/marketing reqs found on one board — Growth Marketing Lead, Product Marketing Lead, Revenue Operations Lead, Outreach Campaign Operations Manager. Q7 satisfied outright.", "source_url": "https://jobs.ashbyhq.com/vendelux/ad171a33-af7d-42b3-86fb-4e3dbb30116a"},
        "D_recent_round": {"points": 3, "evidence": "$50M Series B, July 2026 — two months old", "source_url": "https://firstmark.com/story/vendelux-raises-50m-series-b-to-bring-ai-led-intelligence-to-b2b-events/"},
        "E_channel_fit": {"points": 5, "evidence": "their buyers ARE B2B marketers — the most LinkedIn-native audience that exists — and an events company is structurally a high-touch, physical-artifact buyer (Q10 by definition)"},
    },
    notes="Fresh $50M, four open GTM reqs, and a buyer persona identical to Clue's own. Hiring its way out of the bottleneck right now.",
)

add(
    "Zafran Security", "zafran.io", "V1 B2B SaaS — cybersecurity (exposure management)",
    "New York City, USA (workforce US / Israel / Germany)",
    "Series C — $60M (Dec 2025) + Cisco Investments strategic (Jul 2026); ~$130–136M total",
    {"H1_us": "PASS (Tracxn: 'based in New York City (United States)')", "H2_series_a_plus": "PASS (Series C — scored down per rubric)", "H3_quantifiable_pain": "PASS (Q1 + Q2-style quote)"},
    {
        "A_Q1": {"points": 15, "evidence": "'Senior Manager, ABM & Integrated Campaigns' (USA, published 2026-06-17): 'you will [own] the marketing programs that move our highest priority accounts … design and execute coordinated, multi-channel campaigns'", "source_url": "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf"},
        "A_Q2Q6": {"points": 10, "evidence": "the req says the quiet part out loud: 'If you need a large team and a large budget to do great work, this role is probably not for you.' — small team, big account list, stated by them", "source_url": "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf"},
        "A_Q3": {"points": 0, "evidence": "none found"},
        "A_Q4": {"points": 5, "evidence": "'Zafran Triples ARR in $60M Round to Reinvent Exposure Management with Agentic AI' — Series C led by Menlo Ventures (2025-12-02); Cisco Investments strategic investment added 2026-07-22", "source_url": "https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai"},
        "B_named_account": {"points": 10, "evidence": "'the marketing programs that move our highest priority accounts' — an explicit tiered named-account list", "source_url": "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf"},
        "B_acv": {"points": 8, "evidence": "enterprise exposure-management platform, Sequoia/Menlo/Cisco-backed, $130M raised — large enterprise ACVs", "inferred": True},
        "B_outbound_language": {"points": 7, "evidence": "'translating commercial priorities into focused account-based motions with measurable business impact'", "source_url": "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf"},
        "C_stage": {"points": 6, "evidence": "'Zafran is a series C company based in New York City (United States), founded in 2022 … has raised $130M' — Series C scores 6/10 per rubric §5", "source_url": "https://tracxn.com/d/companies/zafran/__WnETF18DrQMZWAzVpBz7ZMYUDkaMGQwiNkucwmFp6j8"},
        "C_headcount": {"points": 5, "evidence": "Tracxn/LinkedIn place Zafran in the ~100–250 band — inside 30–300", "inferred": True},
        "C_mktteam": {"points": 5, "evidence": "the req's own 'no large team, no large budget' line", "source_url": "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf"},
        "D_no_abm_tool": {"points": 7, "evidence": "no ABM platform named; they are hiring the human instead", "inferred": True},
        "D_leader_or_reqs": {"points": 5, "evidence": "'Reporting to the Head of Growth Marketing' — a GTM leader in seat with a budget", "source_url": "https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf"},
        "D_recent_round": {"points": 3, "evidence": "Cisco Investments strategic investment announced 2026-07-22", "source_url": "https://www.zafran.io/resources/zafran-announces-strategic-investment-from-cisco-investments"},
        "E_channel_fit": {"points": 5, "evidence": "CISO audience, LinkedIn-dense; Cisco relationship implies large-enterprise committees that reward physical executive artifacts"},
    },
    notes="Best single quote in the whole run ('If you need a large team and a large budget…'). Down-weighted only for Series C.",
)

add(
    "Uptiq (UPTIQ, Inc.)", "uptiq.ai", "V3 fintech — AI agents for banks & credit unions",
    "Dallas, TX, USA", "Series B — $25M (Feb 2026), $55M total equity",
    {"H1_us": "PASS", "H2_series_a_plus": "PASS", "H3_quantifiable_pain": "PASS (Q4 + Q6)"},
    {
        "A_Q1": {"points": 0, "evidence": "NOT FOUND — a targeted job-board search for Uptiq marketing/demand-gen reqs returned zero Uptiq postings (it surfaced Glia, MX, Alloy, Relay instead). Absence of evidence, recorded as such.", "source_url": "https://api.exa.ai/search#t_jobs_uptiq"},
        "A_Q2Q6": {"points": 10, "evidence": "'150+ Financial Institutions Trust Us' against a US universe of ~4,500 banks + ~4,600 credit unions — a finite, enumerable named-account market with ~3% penetration", "source_url": "https://www.uptiq.ai/about-us"},
        "A_Q3": {"points": 0, "evidence": "none found"},
        "A_Q4": {"points": 5, "evidence": "'Uptiq Raises $25 Million Series B to Scale Industry-Ready AI Solutions and Launch Qore for Builders' (DALLAS, 2026-02-13)", "source_url": "https://www.businesswire.com/news/home/20260212072104/en/Uptiq-Raises-%2425-Million-Series-B-to-Scale-Industry-Ready-AI-Solutions-and-Launch-Qore-for-Builders"},
        "B_named_account": {"points": 10, "evidence": "sells into named financial institutions ('TransPecos Banks' named as a customer); an ABM case study documents a named-account program", "source_url": "https://www.growthspreeofficial.com/case-studies/case-study-uptiq-ai-building-an-abm-engine-for-modern-financial-leaders"},
        "B_acv": {"points": 8, "evidence": "'over $10 billion in transactions processed' across 150+ FIs — core-banking-adjacent contracts, six figures", "source_url": "https://www.uptiq.ai/about-us", "inferred": True},
        "B_outbound_language": {"points": 7, "evidence": "a published third-party case study titled 'Uptiq.ai ABM Case Study: $400K+ Pipeline' — they already run, and measure, an ABM motion", "source_url": "https://www.growthspreeofficial.com/case-studies/case-study-uptiq-ai-building-an-abm-engine-for-modern-financial-leaders"},
        "C_stage": {"points": 10, "evidence": "'Latest Deal Type Series B · Latest Deal Amount $25M · Employees 129 · Year Founded 2022'", "source_url": "https://pitchbook.com/profiles/company/489650-77"},
        "C_headcount": {"points": 5, "evidence": "129 employees", "source_url": "https://pitchbook.com/profiles/company/489650-77"},
        "C_mktteam": {"points": 5, "evidence": "they outsourced their ABM engine to an agency (GrowthSpree) rather than staffing it — the clearest possible evidence the in-house team is small", "source_url": "https://www.growthspreeofficial.com/case-studies/case-study-uptiq-ai-building-an-abm-engine-for-modern-financial-leaders"},
        "D_no_abm_tool": {"points": 7, "evidence": "an ABM AGENCY is engaged, but no ABM PLATFORM is detected — agency ≠ D3 disqualifier; it is a displaceable line item", "inferred": True},
        "D_leader_or_reqs": {"points": 0, "evidence": "no open GTM req found and no recent GTM-leader hire confirmed"},
        "D_recent_round": {"points": 3, "evidence": "Series B, Feb 2026 — ~6 months old", "source_url": "https://www.uptiq.ai/press-releases/uptiq-raises-25m-to-add-ai-agents-to-bank-workflows"},
        "E_channel_fit": {"points": 5, "evidence": "bank/credit-union executives are a conservative, senior, finite audience where physical mail materially outperforms email — Clue's most differentiated agent aimed at its best-fit audience"},
    },
    notes="The only candidate with PROVEN ABM spend (a $400K-pipeline agency case study). Buys the category already; the question is platform-vs-agency, not whether.",
)

add(
    "Arintra", "arintra.com", "V2 healthcare — autonomous medical coding / revenue assurance",
    "Texas, USA (press release datelined San Francisco, CA)", "Series B — $25M (Aug 26, 2026), ~$46.5–51M total",
    {"H1_us": "PASS", "H2_series_a_plus": "PASS", "H3_quantifiable_pain": "PASS (Q4 + Q6)"},
    {
        "A_Q1": {"points": 0, "evidence": "NOT FOUND — a targeted job-board search returned zero Arintra postings"},
        "A_Q2Q6": {"points": 10, "evidence": "'revenue assurance for America's Health Systems' — a US universe of roughly 6,000 hospitals / ~1,000 health systems: finite, named, enumerable", "source_url": "https://www.arintra.com/resources/press-release/arintra-raises-25m-to-pioneer-revenue-assurance-for-americas-health-systems"},
        "A_Q3": {"points": 0, "evidence": "none found"},
        "A_Q4": {"points": 5, "evidence": "'$25 million Series B funding round, bringing the company's total funding to $51 million. The round is led by Define Ventures' — dated 2026-08-26, FIVE DAYS before this run", "source_url": "https://www.arintra.com/resources/press-release/arintra-raises-25m-to-pioneer-revenue-assurance-for-americas-health-systems"},
        "B_named_account": {"points": 10, "evidence": "'the first and only enterprise AI platform for revenue assurance in healthcare' — health-system enterprise sales is named-account by construction", "source_url": "https://www.arintra.com/resources/press-release/arintra-raises-25m-to-pioneer-revenue-assurance-for-americas-health-systems"},
        "B_acv": {"points": 8, "evidence": "health-system revenue-cycle contracts are six-to-seven figures", "inferred": True},
        "B_outbound_language": {"points": 0, "evidence": "no outbound/ABM language found in cheap discovery"},
        "C_stage": {"points": 10, "evidence": "'Stage Series B | Alive · Total Raised $46.5M · Last Raised $25M | 5 days ago'", "source_url": "https://www.cbinsights.com/company/arintra"},
        "C_headcount": {"points": 5, "evidence": "Series B with a Bengaluru engineering base; US GTM headcount consistent with the band", "inferred": True},
        "C_mktteam": {"points": 5, "evidence": "no marketing leadership surfaced in any cheap probe — consistent with a very small team", "inferred": True},
        "D_no_abm_tool": {"points": 7, "evidence": "no ABM platform detected", "inferred": True},
        "D_leader_or_reqs": {"points": 0, "evidence": "no GTM reqs or new GTM leader found"},
        "D_recent_round": {"points": 3, "evidence": "round is 5 days old — the freshest timing signal in the entire candidate set", "source_url": "https://www.fiercehealthcare.com/finance/arintra-banks-25m-series-b-funding-round-ai-driven-revenue-assurance-platform"},
        "E_channel_fit": {"points": 5, "evidence": "health-system CFO/CIO/rev-cycle committees are exactly the multi-role buying committee Clue maps; printed executive reports are native to hospital finance"},
    },
    notes="Best TIMING in the set (round 5 days old) but zero hiring signal — the fresh-money bet, not the hiring bet. Deliberately selected as the falsification test of my own Q1>Q4 assumption.",
)

add(
    "RevenueCat", "revenuecat.com", "V1 B2B SaaS — mobile subscription infrastructure",
    "San Francisco, CA, USA (remote-first, 25+ countries)", "Series C — $50M (May 2025)",
    {"H1_us": "PASS", "H2_series_a_plus": "PASS", "H3_quantifiable_pain": "PASS (Q1)"},
    {
        "A_Q1": {"points": 15, "evidence": "'Senior Account Based Marketing Manager' ($189K + equity): 'We're hiring a Senior ABM Manager to help RevenueCat speak to, engage, and build pipeline with established consumer apps. This is not your standard \"own the funnel\" demand gen role.'", "source_url": "https://jobs.ashbyhq.com/revenuecat/12fc97f3-d173-4e3a-a652-9afff63a9b56"},
        "A_Q2Q6": {"points": 5, "evidence": "'a remote-first crew of 150+' with a very large addressable market, but the marketing org is no longer tiny", "inferred": True},
        "A_Q3": {"points": 0, "evidence": "none found"},
        "A_Q4": {"points": 0, "evidence": "Series C was May 2025, not GTM-earmarked"},
        "B_named_account": {"points": 10, "evidence": "'established consumer apps' is an explicit named-account upmarket motion", "source_url": "https://jobs.ashbyhq.com/revenuecat/12fc97f3-d173-4e3a-a652-9afff63a9b56"},
        "B_acv": {"points": 8, "evidence": "'we process $12B+ in annual purchase volume' and serve 'the OpenAI mobile team' — enterprise tier exists", "source_url": "https://jobs.ashbyhq.com/revenuecat/12fc97f3-d173-4e3a-a652-9afff63a9b56", "inferred": True},
        "B_outbound_language": {"points": 7, "evidence": "the req exists to 'build pipeline with established consumer apps'", "source_url": "https://jobs.ashbyhq.com/revenuecat/12fc97f3-d173-4e3a-a652-9afff63a9b56"},
        "C_stage": {"points": 6, "evidence": "'$50.0M Series C May 2025' — Series C scores 6/10", "source_url": "https://www.vcbacked.co/company/revenuecat"},
        "C_headcount": {"points": 5, "evidence": "'remote-first crew of 150+'", "source_url": "https://jobs.ashbyhq.com/revenuecat/12fc97f3-d173-4e3a-a652-9afff63a9b56"},
        "C_mktteam": {"points": 2.5, "evidence": "at 150+ headcount with a $189K ABM hire, the marketing org is mid-sized, not tiny", "inferred": True},
        "D_no_abm_tool": {"points": 7, "evidence": "no ABM platform named", "inferred": True},
        "D_leader_or_reqs": {"points": 5, "evidence": "open Senior ABM Manager req in GrowthMarketing", "source_url": "https://jobs.ashbyhq.com/revenuecat/12fc97f3-d173-4e3a-a652-9afff63a9b56"},
        "D_recent_round": {"points": 0, "evidence": "May 2025, >12 months"},
        "E_channel_fit": {"points": 2.5, "evidence": "consumer-app growth leads are LinkedIn-reachable but direct mail and 'executive report' artifacts land far less naturally than with banks/hospitals", "inferred": False},
    },
    notes="Real Q1, but PLG-hybrid economics and the weakest artifact fit in the set. Bench, not select.",
)

add(
    "Translucent (Translucent AI)", "translucent.ai", "V2 healthcare — AI-native healthcare finance",
    "New York, NY, USA (Union Square; 4 days/week in office)", "Series A — $27M led by GV (Mar 11, 2026), $34M total",
    {"H1_us": "PASS", "H2_series_a_plus": "PASS", "H3_quantifiable_pain": "PASS (Q4 + Q6)"},
    {
        "A_Q1": {"points": 0, "evidence": "NOT FOUND — of 18 open roles on their board the visible ones are Delivery, Design, Domain Intelligence, Product and Engineering. No marketing/GTM req surfaced.", "source_url": "https://job-boards.greenhouse.io/translucent/jobs/4038826009"},
        "A_Q2Q6": {"points": 10, "evidence": "'Healthcare providers drive $2.5 trillion in medical expenditures annually — and operate on razor-thin 2–5% margins' against 24 employees", "source_url": "https://job-boards.greenhouse.io/translucent/jobs/4368978009"},
        "A_Q3": {"points": 0, "evidence": "none found"},
        "A_Q4": {"points": 5, "evidence": "'Translucent Announces $27M Series A Led by GV to Tackle Healthcare's Existential Financial Crisis' (2026-03-11)", "source_url": "https://www.businesswire.com/news/home/20260311059455/en/Translucent-Announces-%2427M-Series-A-Led-by-GV-to-Tackle-Healthcares-Existential-Financial-Crisis"},
        "B_named_account": {"points": 10, "evidence": "sells to hospital and health-system finance teams — enumerable named accounts", "source_url": "https://job-boards.greenhouse.io/translucent/jobs/4369098009"},
        "B_acv": {"points": 8, "evidence": "health-system finance platform", "inferred": True},
        "B_outbound_language": {"points": 0, "evidence": "none found"},
        "C_stage": {"points": 10, "evidence": "$27M Series A led by GV, Mar 2026", "source_url": "https://fortune.com/2026/03/11/exclusive-translucent-ai-native-healthcare-finance-startup-raises-27-million-series-a/"},
        "C_headcount": {"points": 2.5, "evidence": "'Translucent AI employs 24 people (+357.1% YoY)' — below the 30–300 target band, though growing violently", "source_url": "https://linkedin.com/company/translucentai"},
        "C_mktteam": {"points": 2.5, "evidence": "at 24 people and hiring engineers/FDEs, marketing is likely 0–1 people — arguably too early to buy", "inferred": True},
        "D_no_abm_tool": {"points": 7, "evidence": "no ABM platform detected", "inferred": True},
        "D_leader_or_reqs": {"points": 0, "evidence": "no GTM req found; the 18 open roles are technical and delivery"},
        "D_recent_round": {"points": 3, "evidence": "Series A Mar 2026, ~6 months", "source_url": "https://www.gv.com/news/translucent-ai-healthcare"},
        "E_channel_fit": {"points": 5, "evidence": "hospital CFO committees; printed artifacts land"},
    },
    notes="Great money, wrong moment: hiring engineers and forward-deployed staff, not marketers. Revisit in two quarters.",
)

add(
    "Alloy", "alloy.com", "V3 fintech — identity/fraud decisioning for banks & fintechs",
    "New York City, USA", "Series C (2021) — stage confirmation NOT re-verified this run",
    {"H1_us": "PASS", "H2_series_a_plus": "PASS (unverified this run — Series C on record)", "H3_quantifiable_pain": "PASS (Q1)"},
    {
        "A_Q1": {"points": 15, "evidence": "'Demand Generation Manager - Mid-Market Banking' ($124k–$146k, New York City) — a demand-gen seat scoped to ONE named vertical is the purest ABM-shaped req there is", "source_url": "https://wellfound.com/jobs/4480918-demand-generation-manager-mid-market-banking"},
        "A_Q2Q6": {"points": 10, "evidence": "mid-market banking in the US is a finite named universe (~4,500 banks) and they are assigning it to a single hire", "inferred": True},
        "A_Q3": {"points": 0, "evidence": "none found"},
        "A_Q4": {"points": 0, "evidence": "no recent round found this run"},
        "B_named_account": {"points": 10, "evidence": "the role is defined by an account segment, not a funnel stage", "source_url": "https://wellfound.com/jobs/4480918-demand-generation-manager-mid-market-banking"},
        "B_acv": {"points": 8, "evidence": "'Identity verification APIs that make KYC/AML effective and simple' sold to banks — six-figure contracts", "inferred": True},
        "B_outbound_language": {"points": 7, "evidence": "a vertical demand-gen seat implies a target list and outbound programs", "inferred": True},
        "C_stage": {"points": 5, "evidence": "Series C on record (2021) — NOT re-verified in this run; scored conservatively and flagged", "inferred": True},
        "C_headcount": {"points": 2.5, "evidence": "not verified this run", "inferred": True},
        "C_mktteam": {"points": 2.5, "evidence": "not verified this run", "inferred": True},
        "D_no_abm_tool": {"points": 0, "evidence": "not checked — a company of Alloy's maturity may well have one"},
        "D_leader_or_reqs": {"points": 5, "evidence": "open vertical demand-gen req, posted ~3 weeks before this run", "source_url": "https://wellfound.com/jobs/4475795-demand-generation-manager-mid-market-banking"},
        "D_recent_round": {"points": 0, "evidence": "none found"},
        "E_channel_fit": {"points": 5, "evidence": "bank buyers; direct mail native"},
    },
    notes="SERENDIPITOUS FIND — surfaced by a tie-break probe aimed at Uptiq, not by a discovery query. Under-verified, hence under-scored; worth a proper look in a future pass.",
)

add(
    "Glia", "glia.com", "V3 fintech — 'Banking AI platform' for community/regional FIs",
    "US (US-Remote req posted); HQ not verified this run", "not verified this run",
    {"H1_us": "UNVERIFIED", "H2_series_a_plus": "UNVERIFIED", "H3_quantifiable_pain": "PARTIAL (Q1 only)"},
    {
        "A_Q1": {"points": 15, "evidence": "'Growth Marketing Manager @ Glia', US-Remote, Marketing dept", "source_url": "https://jobs.ashbyhq.com/glia/4cdacf7f-a3c1-45fc-8997-eb180c4de7b1"},
        "A_Q2Q6": {"points": 10, "evidence": "'empowering community and regional financial institutions' — the same finite ~9,000-institution universe as Uptiq", "source_url": "https://jobs.ashbyhq.com/glia/4cdacf7f-a3c1-45fc-8997-eb180c4de7b1"},
        "A_Q3": {"points": 0, "evidence": "none"},
        "A_Q4": {"points": 0, "evidence": "not checked"},
        "B_named_account": {"points": 10, "evidence": "'the #1 Banking AI platform' selling to named FIs", "source_url": "https://jobs.ashbyhq.com/glia/4cdacf7f-a3c1-45fc-8997-eb180c4de7b1", "inferred": True},
        "B_acv": {"points": 8, "evidence": "banking platform contracts", "inferred": True},
        "B_outbound_language": {"points": 0, "evidence": "not established"},
        "C_stage": {"points": 0, "evidence": "H2 NOT VERIFIED — cannot award stage points without a confirmed round"},
        "C_headcount": {"points": 0, "evidence": "not verified"},
        "C_mktteam": {"points": 0, "evidence": "not verified"},
        "D_no_abm_tool": {"points": 0, "evidence": "not checked"},
        "D_leader_or_reqs": {"points": 5, "evidence": "open Growth Marketing Manager req", "source_url": "https://jobs.ashbyhq.com/glia/4cdacf7f-a3c1-45fc-8997-eb180c4de7b1"},
        "D_recent_round": {"points": 0, "evidence": "not checked"},
        "E_channel_fit": {"points": 5, "evidence": "community-bank executives — direct mail native"},
    },
    notes="SERENDIPITOUS FIND. Score is artificially depressed by unverified gates — deliberately NOT laundered into a clean number.",
)

# ============================================================ DROPPED AT A GATE

for nm, dom, why in [
    ("Oscilar", "oscilar.com", "H2 AMBIGUOUS → excluded. Strongest non-selected candidate. Palo Alto CA (PASS H1), 150–200 employees (+130% YoY), open 'Outbound Marketing Manager' req at $155K–$184K (a Tier-1 Q1), sells to banks/fintechs (finite market). BUT: 'Oscilar is entirely self-funded, backed by $20 million that Narkhede and the company's other co-founder, Sachin Kulkarni, themselves contributed' (TechCrunch 2023-03-30) and a targeted 2024+ search found NO external priced round. CB Insights/aVenture label it 'Series A' on the strength of that self-funding. Under H2 as written ('a named priced round with a date and at least one named investor') it fails. Recorded as a rule blind-spot, not a judgement about the company."),
    ("Ideals (iDeals)", "idealsvdr.com", "H1 — global company; parallel ABM reqs posted for United States AND Brazil, HQ not US; also no venture round (H2)."),
    ("Filigran", "filigran.io", "H1 — 'Location: France' on the ABM req."),
    ("Airwallex", "airwallex.com", "H1 — Australia/Hong Kong HQ; role is 'Global ABM'."),
    ("Xero", "xero.com", "H1 + D7 — New Zealand, publicly listed."),
    ("Smarsh", "smarsh.com", "D7 — PE-owned, >1,000 headcount."),
    ("Ncontracts", "ncontracts.com", "D7 — PE-backed, 5,000+ customers, Nashville; strong Q1 (open ABM Manager req, $100–120K) but wrong stage."),
    ("CentralReach", "centralreach.com", "D7 — PE-owned healthcare software, 200,000+ users."),
    ("ConnectWise", "connectwise.com", "D7 — PE-owned."),
    ("Auctane", "auctane.com", "D7 — PE-owned."),
    ("CI&T", "ciandt.com", "H1 + D7 — Brazilian, publicly listed."),
    ("Demandbase", "demandbase.com", "D6 — a direct competitor (enterprise ABM platform)."),
    ("Sprouts.ai", "sprouts.ai", "D6 — 'revenue agents … for B2B enterprises'; also pre-Series-A ($9M pre-Series A, 2026-05)."),
    ("Directive / Seer Interactive / Ignitium / Revvgrowth / Forefront ABM / Trevon / PrecisionPoint / Khronos", "various", "D6+H2 — agencies selling ABM services; not venture-funded (H2) and mostly competitors-by-substitution (D6). Confirms icp.md §2's ruling that V4 rarely survives the gates."),
    ("Factors.ai / Abmatic / Octave / Clearcue / GR0 / Amy / The Smarketers / UserGems", "various", "D6 — surfaced by the A1 search for Clue itself; all sell ABM/GTM-agent tooling."),
    ("Sift Healthcare", "sifthealthcare.com", "Stale — last confirmed round $20M Series B (2024-05); outside the 24-month freshness preference. Watch."),
    ("CertifyOS", "certifyos.com", "Stale — $14.5M Series A (2022-09)."),
    ("Prosper AI", "getprosper.ai", "Not dropped on a gate — $30M Series A led by a16z (2026-06-22) is a clean H2 pass and the pain quote is excellent ('the workforce in US hospitals and physician offices is administrative staff, a cost that tops $450 billion annually'). US HQ NOT verified this run, and no GTM hiring signal found. Strong bench; ran out of verification budget before it could be scored."),
    ("Aligned / Actively / LetterAI / Dust / InstaLILY / Genspark", "various", "Deferred — all surfaced by the funding-signal query with real Series B rounds, but each needs an H1 (US HQ) check and a D6 competitor check (several sell revenue/GTM AI) before scoring. Not enough evidence for an honest score in Agent A's budget."),
    ("Naehas / adapfin / Candescent / glide / fuse / vikar / spiral / akuvo / linker finance", "various", "Deferred — fintech vendors surfaced by d7; most results were LinkedIn stubs with no funding or HQ evidence in the returned text. Insufficient evidence to score honestly."),
    ("Zania / Optro / Builder Prime / Softr / Apera / MX Technologies / Relay", "various", "Deferred/dropped — surfaced incidentally by tie-break probes. Apera (Vancouver) and Relay (Toronto) fail H1; MX and Optro are later-stage; Zania, Builder Prime and Softr are plausible but unverified."),
]:
    add(nm, dom, "—", "—", "—", {}, dropped=why)

# ============================================================ SELECTION

scored = [c for c in CANDIDATES if c["disposition"] == "scored"]
scored.sort(key=lambda c: -c["fit_score"])

SELECTED = ["Cogent Security, Inc.", "Harmonic Security, Inc.", "Zafran Security", "Vendelux", "Uptiq (UPTIQ, Inc.)"]
alt = "Arintra"

out = {
    "run": "arv2-smoke-cluehq / Agent A",
    "date": "2026-08-31",
    "client": {"name": "Clue", "domain": "cluehq.ai", "product": "Agentic ABM for modern GTM teams"},
    "rubric_source": "icp.md §5",
    "hard_gates": {"H1": "US HQ", "H2": "Series A or above", "H3": "quantifiable pain"},
    "exclusions_applied": ["probook.ai", "lassie.ai", "avoca", "Insight Health", "Clue/cluehq.ai"],
    "counts": {
        "scored": len(scored),
        "dropped_at_gate": len([c for c in CANDIDATES if c["disposition"] == "dropped"]),
        "selected": 5,
    },
    "ranking": [{"name": c["name"], "fit_score": c["fit_score"], "band": c["band"]} for c in scored],
    "selected_5": SELECTED,
    "alternate": alt,
    "candidates": CANDIDATES,
}
json.dump(out, open("candidates.json", "w"), indent=2)

print("RANKING")
for c in scored:
    mark = "  <== SELECTED" if c["name"] in SELECTED else ""
    print(f"  {c['fit_score']:5.1f}  [{c['band']:>12}]  {c['name']}{mark}")
print(f"\nscored={len(scored)} dropped={len([c for c in CANDIDATES if c['disposition']=='dropped'])}")
L.timing_record("A4d_scoring", time.time() - t0, "rubric application + candidates.json")
