"""Step 2 — Apollo org enrich on the picked account (1 credit)."""

import json
import sys

from clue_lib import apollo

domain = sys.argv[1] if len(sys.argv) > 1 else "charlestongi.com"
label = sys.argv[2] if len(sys.argv) > 2 else "step2_apollo_org"

r = apollo(f"/organizations/enrich?domain={domain}", label=label, credits=1)
org = r.get("organization") or {}
if not org:
    print("NO ORGANIZATION IN RESPONSE:", json.dumps(r)[:800])
else:
    keep = [
        "id",
        "name",
        "website_url",
        "primary_domain",
        "linkedin_url",
        "founded_year",
        "industry",
        "industries",
        "keywords",
        "estimated_num_employees",
        "annual_revenue_printed",
        "total_funding_printed",
        "latest_funding_stage",
        "raw_address",
        "street_address",
        "city",
        "state",
        "postal_code",
        "country",
        "phone",
        "primary_phone",
        "sanitized_phone",
        "retail_location_count",
        "owned_by_organization_id",
        "owned_by_organization",
        "ultimate_parent_organization",
        "publicly_traded_symbol",
        "short_description",
        "technology_names",
        "departmental_head_count",
        "organization_headcount_six_month_growth",
        "organization_headcount_twelve_month_growth",
    ]
    for k in keep:
        if k in org and org[k] not in (None, "", [], {}):
            v = org[k]
            if isinstance(v, (dict, list)):
                v = json.dumps(v)[:600]
            print(f"  {k}: {v}")
    print("  ALL KEYS:", sorted(org.keys()))
