"""Step 1 — discovery against the TIGHTENED v3 ICP.

Series A / A-extension ONLY (raised within ~24 months), US B2B vertical SaaS/AI selling into a
fragmented SMB vertical, ACTIVELY HIRING (GTM especially), showing buying-intent signals.

Three Exa searches, type=auto, 10 results, text bundled ($0.007 each, v2-measured).
"""

import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

QUERIES = [
    (
        "d1_seriesA_vertical_ai_smb",
        "US startup announced a Series A round in 2026 building AI software for independent "
        "small businesses in a fragmented vertical — dental practices, veterinary clinics, HVAC "
        "and plumbing contractors, auto repair shops, law firms, pharmacies, restaurants",
    ),
    (
        "d2_seriesA_gtm_hiring",
        "Series A vertical AI SaaS startup hiring its first go-to-market team in 2026 — founding "
        "account executive, head of growth, demand generation, outbound prospecting and "
        "list-building for thousands of small business accounts",
    ),
    (
        "d3_founder_led_sales_scaling",
        "founder of a Series A vertical software company in 2026 describing founder-led sales "
        "reaching its limit and building a repeatable outbound go-to-market engine to reach "
        "tens of thousands of small business customers",
    ),
]

for label, q in QUERIES:
    payload = {
        "query": q,
        "type": "auto",
        "numResults": 10,
        "startPublishedDate": "2025-06-01T00:00:00.000Z",
        "contents": {"text": {"maxCharacters": 3000}},
    }
    r = C.exa(payload, label=label)
    for res in (r.get("results") or [])[:10]:
        print(
            f"    - {res.get('title')} | {res.get('url')} | pub={res.get('publishedDate')}",
            flush=True,
        )

print("\nTOTAL SPEND SO FAR:", C.total_spend())
