"""Step 2 — lock the picked account's real domain (one cheap Exa call), then Apollo org enrich.

Picked account: Lassie (AI for dental / doctors' offices, SF, $35M a16z round Jun-2026).
Name-collision risk is real ("Lassie" is also a Swedish pet-insurance brand), so the domain is
locked against a primary source BEFORE the expensive deep call is spent.
"""

import json
import sys

from clue_lib import apollo, exa, save_raw, total_spend

if "--enrich-only" not in sys.argv:
    r = exa(
        {
            "query": (
                "Lassie AI for dental practices and doctors' offices official website, the San "
                "Francisco startup founded by Steijn Pelle and Frederic Renken that raised $35M "
                "from a16z"
            ),
            "type": "fast",
            "numResults": 8,
            "contents": {"text": {"maxCharacters": 800}},
            "stream": False,
        },
        label="d4_domain_lock",
        timeout=120,
    )
    for item in r.get("results") or []:
        print("-", item.get("url"), "|", (item.get("title") or "")[:90], flush=True)
    print("spend so far $", total_spend(), flush=True)
    sys.exit(0)

domain = sys.argv[sys.argv.index("--domain") + 1]
org = apollo(
    f"/organizations/enrich?domain={domain}",
    label=f"apollo_org_enrich_{domain.replace('.', '_')}",
    credits=1,
)
o = org.get("organization") or {}
keep = {
    k: o.get(k)
    for k in (
        "id",
        "name",
        "website_url",
        "primary_domain",
        "linkedin_url",
        "twitter_url",
        "founded_year",
        "industry",
        "industries",
        "keywords",
        "estimated_num_employees",
        "annual_revenue",
        "annual_revenue_printed",
        "total_funding",
        "total_funding_printed",
        "latest_funding_round_date",
        "latest_funding_stage",
        "funding_events",
        "current_technologies",
        "technology_names",
        "departmental_head_count",
        "organization_headcount_six_month_growth",
        "organization_headcount_twelve_month_growth",
        "organization_headcount_twenty_four_month_growth",
        "raw_address",
        "street_address",
        "city",
        "state",
        "postal_code",
        "country",
        "phone",
        "short_description",
        "seo_description",
        "logo_url",
        "publicly_traded_symbol",
        "owned_by_organization_id",
    )
}
save_raw("apollo_org_normalized", keep)
print(json.dumps({k: v for k, v in keep.items() if k != "current_technologies"}, indent=2)[:4000])
print("\nTECHNOLOGIES:", (keep.get("technology_names") or [])[:60])
print("spend so far $", total_spend())
