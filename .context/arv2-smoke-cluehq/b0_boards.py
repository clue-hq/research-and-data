"""B0 — the $0 probe that answers Agent A's biggest unknown: IS THE REQ STILL OPEN?

Ashby's public posting API lists only CURRENTLY LIVE jobs. If A's req id is in the board, the
req is open today; if it is absent, it was filled or pulled. Costs nothing, takes ~1s per board.
Also fetches each account's own site root by plain urllib (the fetch-ladder rung 1 data point).
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

BOARDS = {
    "zafran": ("zafran-security", "c879de63-c999-47cc-99a3-e35cf9ba7cdf",
               "Senior Manager, ABM & Integrated Campaigns"),
    "cogent": ("cogent-security", "8ed749ff-cf21-47ec-815d-36af19ab389d",
               "Head of Demand Generation"),
    "harmonic": ("harmonic-security-inc", "f568f331-f4ea-4328-a690-03772941f561",
                 "Account-Based Marketing Manager, Strategic Accounts"),
    "vendelux": ("vendelux", "7dfeabd3-7595-490b-af19-dff052216d67",
                 "Outreach Campaign Operations Manager"),
    "uptiq": ("uptiq", None, None),
    "arintra": ("arintra", None, None),
}

SITES = {
    "zafran": "https://www.zafran.io",
    "cogent": "https://www.cogent.com",
    "harmonic": "https://www.harmonic.security",
    "vendelux": "https://www.vendelux.com",
    "uptiq": "https://www.uptiq.ai",
}

t_phase = time.time()
out = {}

for key, (slug, req_id, req_title) in BOARDS.items():
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    t0 = time.time()
    status, hdrs, text, elapsed = C._request(
        url,
        headers={"accept": "application/json", "User-Agent": C.BROWSER_UA},
        timeout=60,
        retries=2,
    )
    board = json.loads(text) if status == 200 else {"_unparsed": text[:1500]}
    board["_http_status"] = status
    C.save_raw(f"b0_ashby_{key}", board)
    C.ledger_append(
        {
            "provider": "ashby_public",
            "label": f"b0_ashby_{key}",
            "op": f"GET posting-api/job-board/{slug}",
            "http": status,
            "elapsed_s": elapsed,
            "cost_usd": 0.0,
        }
    )
    jobs = board.get("jobs") or []
    hit = [j for j in jobs if j.get("id") == req_id] if req_id else []
    out[key] = {
        "slug": slug,
        "http": status,
        "n_jobs": len(jobs),
        "req_id": req_id,
        "req_title": req_title,
        "req_still_open": bool(hit),
        "req_row": hit[0] if hit else None,
        "all_jobs": [
            {
                "id": j.get("id"),
                "title": j.get("title"),
                "department": j.get("department"),
                "team": j.get("team"),
                "location": j.get("location"),
                "publishedAt": j.get("publishedAt"),
                "comp": (j.get("compensation") or {}).get("compensationTierSummary"),
                "url": j.get("jobUrl"),
            }
            for j in jobs
        ],
    }
    print(f"\n=== {key} [{slug}] http={status} jobs={len(jobs)} {elapsed}s")
    if req_id:
        print(f"    REQ '{req_title}' STILL OPEN? -> {'YES' if hit else 'NO / not on board'}")
    for j in jobs:
        print(f"    [{j.get('department')}/{j.get('team')}] {j.get('title')} | "
              f"{j.get('location')} | pub={j.get('publishedAt')} | "
              f"{(j.get('compensation') or {}).get('compensationTierSummary')}")
    time.sleep(0.3)

# fetch-ladder rung 1: does a plain urllib GET with a browser UA work on each account site?
print("\n=== live site fetches (fetch-ladder rung 1) ===")
for key, url in SITES.items():
    r = C.live_fetch(url, label=f"site_{key}")
    out.setdefault(key, {})["live_site"] = {
        "url": url, "http": r["status"], "bytes": len(r["text"]), "elapsed_s": r["elapsed_s"],
        "server": (r["headers"].get("Server") or r["headers"].get("server")),
    }

json.dump(out, open("b0_boards.json", "w"), indent=2)
C.timing_record("B0_ashby_boards_and_live_sites", time.time() - t_phase,
                "free: 6 Ashby boards + 5 live site fetches")
print(f"\nPHASE B0 {round(time.time()-t_phase,1)}s  spend={C.total_spend()} "
      f"credits={C.total_credits()}")
