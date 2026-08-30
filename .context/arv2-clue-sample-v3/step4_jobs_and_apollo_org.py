"""Step 4 — the hiring index in full (Ashby public posting API, $0) + Apollo org enrich (1 credit).

The 6 open GTM reqs are the run's strongest P1 buying-intent evidence, and they must be QUOTED,
so the full descriptions are fetched from Ashby's public job-board API rather than paid for again.
Apollo supplies the tier-1 firmographic/technographic skeleton (and the ABM-tooling-absence read).
"""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

# --- Ashby public job board API (no key, no cost) ---------------------------------------------
url = "https://api.ashbyhq.com/posting-api/job-board/probook?includeCompensation=true"
status, hdrs, text, elapsed = C._request(url, headers={"accept": "application/json"}, timeout=90)
try:
    board = json.loads(text)
except Exception:
    board = {"_unparsed": text[:4000]}
board["_http_status"] = status
C.save_raw("gt2_ashby_job_board_api", board)
C.ledger_append(
    {
        "provider": "ashby_public",
        "label": "gt2_ashby_job_board_api",
        "op": "GET posting-api/job-board/probook",
        "http": status,
        "elapsed_s": elapsed,
        "cost_usd": 0.0,
        "credits": 0,
    }
)
jobs = board.get("jobs") or []
print(f"ashby http={status} jobs={len(jobs)}")
for j in jobs:
    print(
        f"  - [{j.get('department')}/{j.get('team')}] {j.get('title')} | {j.get('location')} "
        f"| published={j.get('publishedAt')} | {j.get('jobUrl')}"
    )
    comp = j.get("compensation") or {}
    if comp.get("compensationTierSummary"):
        print(f"      comp: {comp['compensationTierSummary']}")

# --- Apollo organizations/enrich (1 credit) ----------------------------------------------------
org = C.apollo(
    "/organizations/enrich?domain=probook.ai",
    label="apollo_org_enrich",
    credits=1,
)
o = org.get("organization") or {}
print("\nAPOLLO ORG")
for k in (
    "id",
    "name",
    "website_url",
    "primary_domain",
    "linkedin_url",
    "founded_year",
    "estimated_num_employees",
    "raw_address",
    "phone",
    "industry",
    "annual_revenue_printed",
    "publicly_traded_symbol",
):
    print(f"  {k}: {o.get(k)}")
print("  departmental_head_count:", json.dumps(o.get("departmental_head_count")))
print("  funding_events:", json.dumps(o.get("funding_events"))[:1200])
techs = [t.get("name") for t in (o.get("current_technologies") or [])]
print(f"  technologies ({len(techs)}):", techs)
print("  keywords:", (o.get("keywords") or [])[:30])
print("\nTOTAL:", C.total_spend())
