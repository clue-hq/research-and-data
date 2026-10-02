"""Arms W5 and W3 — two websets over the same ICP, discovery only, polled to idle.

Usage: run_websets.py [W5|W3|both]   (default both). Each arm asks for 25 companies, which is the
free tier's per-webset cap and 250 credits at most (10 credits per all-green result).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exa_common import ICP_TEXT, ledger_append, request, save_raw  # noqa: E402

BASE = "https://api.exa.ai/websets/v0/websets"
COUNT = 25
POLL_S = 15
MAX_WAIT_S = 30 * 60

#: The ICP's hard gates as Websets criteria. W5 = all five (the four gates + the vertical).
#: W3 = only the three a public page can answer; hiring and intent stay with our own probe.
CRITERIA = {
    "geography": "Company is headquartered in the United States",
    "stage": (
        "Company announced a Series A or Series A extension funding round within the last 24 "
        "months (not seed, not Series B or later, not a growth round)"
    ),
    "vertical": (
        "Company sells B2B software or AI to independent small businesses in one fragmented "
        "vertical such as dental practices, veterinary clinics, HVAC and plumbing contractors, "
        "auto repair shops, law firms, pharmacies, restaurants or trucking"
    ),
    "hiring": (
        "Company currently lists at least one open go-to-market job (sales, marketing, growth, "
        "SDR or BDR, demand generation, partnerships) on its own careers page or ATS board"
    ),
    "intent": (
        "Company shows a buying-intent signal for outbound or account-based prospecting: a GTM "
        "job description mentioning list-building or outbound, a founder stating founder-led "
        "sales is at its limit, or no ABM platform in use"
    ),
}
ARMS = {
    "W5": ["geography", "stage", "vertical", "hiring", "intent"],
    "W3": ["geography", "stage", "vertical"],
}


def create(arm: str) -> str:
    body = {
        "title": f"ARV2 R4 discovery experiment {arm} 2026-09-10",
        "externalId": f"arv2-r4-discovery-{arm.lower()}-2026-09-10",
        "search": {
            "query": ICP_TEXT,
            "count": COUNT,
            "entity": {"type": "company"},
            "criteria": [{"description": CRITERIA[key]} for key in ARMS[arm]],
        },
    }
    status, out = request("POST", BASE, body)
    out["_request"] = body
    save_raw(f"webset_{arm}_create", out)
    ledger_append({"arm": arm, "provider": "exa_websets", "label": "create", "http": status,
                   "elapsed_s": out.get("_elapsed_s"), "webset_id": out.get("id")})
    print(f"{arm}: create http={status} id={out.get('id')} status={out.get('status')}")
    if status not in (200, 201):
        raise SystemExit(f"{arm}: create failed: {json.dumps(out)[:800]}")
    return out["id"]


def poll(arm: str, webset_id: str) -> dict:
    started = time.monotonic()
    while True:
        status, out = request("GET", f"{BASE}/{webset_id}")
        search = (out.get("searches") or [{}])[0]
        progress = search.get("progress") or {}
        elapsed = int(time.monotonic() - started)
        print(f"{arm}: t={elapsed}s webset={out.get('status')} search={search.get('status')} "
              f"found={progress.get('found')} analyzed={progress.get('analyzed')} "
              f"completion={progress.get('completion')}")
        if out.get("status") == "idle" or elapsed > MAX_WAIT_S:
            save_raw(f"webset_{arm}_final", out)
            ledger_append({"arm": arm, "provider": "exa_websets", "label": "final",
                           "webset_status": out.get("status"), "search_status": search.get("status"),
                           "found": progress.get("found"), "analyzed": progress.get("analyzed"),
                           "time_to_idle_s": elapsed})
            return out
        time.sleep(POLL_S)


def items(arm: str, webset_id: str) -> list[dict]:
    rows: list[dict] = []
    cursor = None
    while True:
        url = f"{BASE}/{webset_id}/items?limit=100" + (f"&cursor={cursor}" if cursor else "")
        _, out = request("GET", url)
        rows.extend(out.get("data") or [])
        if not out.get("hasMore"):
            break
        cursor = out.get("nextCursor")
    save_raw(f"webset_{arm}_items", rows)
    green = sum(1 for r in rows if all(e.get("satisfied") == "yes" for e in r.get("evaluations") or []))
    ledger_append({"arm": arm, "provider": "exa_websets", "label": "items", "items": len(rows),
                   "all_green": green, "credits_est": green * 10})
    print(f"{arm}: items={len(rows)} all_green={green} credits_est={green * 10}")
    return rows


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    arms = list(ARMS) if which == "both" else [which]
    ids = {arm: create(arm) for arm in arms}
    for arm, webset_id in ids.items():
        poll(arm, webset_id)
        items(arm, webset_id)
