"""Arm S — the v3 proof of concept's three discovery searches, verbatim, re-run today."""

from __future__ import annotations

import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from exa_common import ledger_append, request, save_raw  # noqa: E402

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

for label, query in QUERIES:
    payload = {
        "query": query,
        "type": "auto",
        "numResults": 10,
        "startPublishedDate": "2025-06-01T00:00:00.000Z",
        "contents": {"text": {"maxCharacters": 3000}},
    }
    status, out = request("POST", "https://api.exa.ai/search", payload)
    out["_request"] = payload
    save_raw(f"search_{label}", out)
    cost = (out.get("costDollars") or {}).get("total")
    ledger_append(
        {"arm": "S", "provider": "exa_search", "label": label, "http": status,
         "elapsed_s": out.get("_elapsed_s"), "cost_usd": cost}
    )
    print(f"search[{label}] http={status} cost={cost} results={len(out.get('results') or [])}")
    for res in out.get("results") or []:
        print(f"    - {res.get('title')} | {res.get('url')} | pub={res.get('publishedDate')}")
