"""Step 1 — Exa discovery of Clue-ICP accounts (buyers FOR Clue).

ICP: US vertical B2B SaaS / AI startups, seed-Series B, ~10-200 employees, selling high-touch
products into FRAGMENTED SMB/mid-market verticals (medical, dental, legal, logistics,
construction back-office); founder-led or first-GTM-hire sales; outbound + direct mail;
no enterprise ABM platform installed.
"""

import json
import os
import time

from clue_lib import HERE, exa, save_raw, total_spend

SYS = (
    "You are sourcing target accounts for an AI-native account-based-marketing (ABM) platform. "
    "Return real, currently-operating US venture-backed startups (seed to Series B, roughly "
    "10-200 employees) that build vertical B2B software or AI products sold to FRAGMENTED "
    "SMB/mid-market buyers such as medical practices, dental groups, law firms, trucking and "
    "logistics operators, home-services or construction back-offices. Prefer companies with "
    "recent funding, visible go-to-market hiring, and a founder-led or first-sales-hire motion. "
    "Exclude enterprise incumbents, public companies, pure consumer apps, and companies over "
    "1,000 employees. Exclude Insight Health. Ground every company in a real page."
)

CONTENTS = {
    "text": {"maxCharacters": 1200},
    "highlights": {
        "query": "funding round, employees, hiring sales GTM, sells to practices/firms/SMBs",
        "maxCharacters": 800,
    },
}

QUERIES = [
    (
        "d1_vertical_ai_practices",
        "seed or Series A startup building AI software for independent medical, dental or "
        "veterinary practices, raised funding in the last 18 months, hiring its first sales hires",
    ),
    (
        "d2_vertical_ai_smb_services",
        "vertical AI SaaS startup selling to law firms, trucking companies, or home services "
        "contractors, recently raised seed or Series A, founder-led sales, hiring a founding "
        "account executive",
    ),
    (
        "d3_gtm_hiring_outbound",
        "early stage B2B vertical software company hiring head of growth or founding AE to run "
        "outbound to small business customers 2026",
    ),
]

results = {}
for label, q in QUERIES:
    print("discovery:", label, flush=True)
    r = exa(
        {
            "query": q,
            "type": "auto",
            "numResults": 10,
            "systemPrompt": SYS,
            "contents": CONTENTS,
            "stream": False,
        },
        label=label,
        timeout=180,
    )
    results[label] = r
    time.sleep(1.0)

rows = []
for label, r in results.items():
    for item in r.get("results") or []:
        rows.append(
            {
                "query": label,
                "title": item.get("title"),
                "url": item.get("url"),
                "published": item.get("publishedDate"),
                "author": item.get("author"),
                "highlights": item.get("highlights"),
                "text": (item.get("text") or "")[:900],
            }
        )
save_raw("d_candidates_flat", rows)
print("candidates:", len(rows), "spend so far $", total_spend(), flush=True)
for row in rows:
    print("-", row["url"], "|", (row["title"] or "")[:100], flush=True)
