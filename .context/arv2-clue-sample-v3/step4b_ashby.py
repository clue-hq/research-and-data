"""Step 4b — Ashby public posting API with a browser UA (urllib's default UA gets a 403). $0."""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

url = "https://api.ashbyhq.com/posting-api/job-board/probook?includeCompensation=true"
status, hdrs, text, elapsed = C._request(
    url,
    headers={
        "accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    },
    timeout=90,
)
board = json.loads(text) if status == 200 else {"_unparsed": text[:2000]}
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
print(f"http={status} jobs={len(jobs)}")
for j in jobs:
    comp = (j.get("compensation") or {}).get("compensationTierSummary")
    print(
        f"[{j.get('department')}] {j.get('title')} | {j.get('location')} | "
        f"pub={j.get('publishedAt')} | comp={comp}\n    {j.get('jobUrl')}"
    )
