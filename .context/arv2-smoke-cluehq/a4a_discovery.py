"""A4a — discovery. 8 Exa searches across 5 angles. Every query + every result recorded verbatim.

Each search carries contents.text (1200 chars) so scoring rests on real page text, not on titles.
Cost per search ~= $0.007 (neural) + $0.001/result contents.
"""

import json
import time

import clue_lib as L

t_phase = time.time()

# angle -> (label, payload). Recorded verbatim into discovery_raw.json.
QUERIES = [
    (
        "semantic_icp",
        "d1_semantic_saas",
        {
            "query": (
                "US Series B B2B SaaS company selling to large enterprise named accounts with a "
                "small marketing team running account-based marketing campaigns"
            ),
            "type": "auto",
            "numResults": 10,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "semantic_icp_vertical_health",
        "d2_semantic_health",
        {
            "query": (
                "Series A or Series B US healthcare software company selling to hospitals, health "
                "systems and payers with an enterprise sales team and a small marketing team"
            ),
            "type": "auto",
            "numResults": 10,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "signal_first_job_req_abm",
        "d3_jobs_abm",
        {
            "query": (
                "Account Based Marketing Manager job opening: build and maintain the target "
                "account list, research accounts, run 1:1 ABM campaigns for our top accounts"
            ),
            "type": "auto",
            "numResults": 10,
            "includeDomains": [
                "boards.greenhouse.io",
                "job-boards.greenhouse.io",
                "jobs.lever.co",
                "jobs.ashbyhq.com",
                "ashbyhq.com",
            ],
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "signal_first_job_req_demandgen",
        "d4_jobs_demandgen",
        {
            "query": (
                "Demand Generation Manager job description: account research, target account "
                "lists, personalized outbound campaigns, direct mail and field marketing"
            ),
            "type": "auto",
            "numResults": 10,
            "includeDomains": [
                "boards.greenhouse.io",
                "job-boards.greenhouse.io",
                "jobs.lever.co",
                "jobs.ashbyhq.com",
                "ashbyhq.com",
            ],
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "funding_signal_gtm_earmark",
        "d5_funding_gtm",
        {
            "query": (
                "raises Series B funding to expand its enterprise go-to-market and sales team, "
                "B2B software company, United States"
            ),
            "type": "auto",
            "numResults": 10,
            "startPublishedDate": "2025-09-01T00:00:00.000Z",
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "founder_pain_post",
        "d6_founder_pain",
        {
            "query": (
                "we spent weeks researching accounts to personalize outbound and only shipped a "
                "handful of campaigns — B2B marketing leader writing about ABM being too much work"
            ),
            "type": "auto",
            "numResults": 10,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "vertical_fintech_finite_market",
        "d7_fintech_banks",
        {
            "query": (
                "venture-backed US fintech software company selling software to banks and credit "
                "unions, enterprise deals, named account sales"
            ),
            "type": "auto",
            "numResults": 10,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "agency_second_order",
        "d8_agency",
        {
            "query": (
                "venture-backed US B2B marketing services company running account-based marketing "
                "programs for enterprise software clients"
            ),
            "type": "auto",
            "numResults": 10,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
]

out = []
for angle, label, payload in QUERIES:
    t0 = time.time()
    resp = L.exa(payload, label=label)
    rec = {
        "angle": angle,
        "label": label,
        "query_verbatim": payload["query"],
        "payload": payload,
        "http": resp.get("_http_status"),
        "elapsed_s": resp.get("_elapsed_s"),
        "cost_usd": (resp.get("costDollars") or {}).get("total"),
        "results": [
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "publishedDate": r.get("publishedDate"),
                "author": r.get("author"),
                "text": (r.get("text") or ""),
            }
            for r in (resp.get("results") or [])
        ],
    }
    out.append(rec)
    L.timing_record(f"A4a_search_{label}", time.time() - t0, angle)
    time.sleep(1.1)  # 10 req/s limit; pace ~1/s

json.dump(out, open("discovery_raw.json", "w"), indent=2)
el = time.time() - t_phase
L.timing_record("A4a_discovery_searches", el, f"{len(QUERIES)} exa searches, 5 angles")
print(f"A4a done in {el:.1f}s; total spend ${L.total_spend()}")
