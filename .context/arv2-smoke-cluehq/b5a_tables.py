"""B5a — build the timing table, the money table and the scraping verdict from the ledgers.

Merges Agent A's cost_ledger.json/timing.json with Agent B's cost_ledger_b.json/timing_b.json.
Every number here comes from a real recorded response.
"""

import json
import time
from collections import defaultdict

A_LED = json.load(open("cost_ledger.json"))["calls"]
B_LED = json.load(open("cost_ledger_b.json"))
A_TIM = json.load(open("timing.json"))["phases"]
B_TIM = json.load(open("timing_b.json"))["phases"]

ACCTS = ["zafran", "cogent", "harmonic", "vendelux", "uptiq"]


def agg(rows, tag):
    out = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0, "credits": 0.0, "wall_s": 0.0,
                               "http_ok": 0, "http_bad": 0})
    for r in rows:
        p = out[r.get("provider", "?")]
        p["calls"] += 1
        p["cost_usd"] += float(r.get("cost_usd") or 0)
        p["credits"] += float(r.get("credits") or 0)
        p["wall_s"] += float(r.get("elapsed_s") or 0)
        if 200 <= int(r.get("http") or 0) < 300:
            p["http_ok"] += 1
        else:
            p["http_bad"] += 1
    for v in out.values():
        v["cost_usd"] = round(v["cost_usd"], 4)
        v["wall_s"] = round(v["wall_s"], 1)
    return {"agent": tag, "by_provider": dict(out),
            "total_cost_usd": round(sum(v["cost_usd"] for v in out.values()), 4),
            "total_credits": round(sum(v["credits"] for v in out.values()), 2),
            "total_wall_s": round(sum(v["wall_s"] for v in out.values()), 1),
            "total_calls": sum(v["calls"] for v in out.values())}


A, B = agg(A_LED, "A"), agg(B_LED, "B")

# ---- per-account money + time attribution (label prefixes carry the account key)
per_acct = {k: {"cost_usd": 0.0, "credits": 0.0, "provider_wall_s": 0.0, "calls": 0}
            for k in ACCTS}
unattributed = {"cost_usd": 0.0, "credits": 0.0, "provider_wall_s": 0.0, "calls": 0}
for r in B_LED:
    lab = (r.get("label") or "") + " " + (r.get("op") or "")
    hit = next((k for k in ACCTS if k in lab.lower()), None)
    tgt = per_acct[hit] if hit else unattributed
    tgt["cost_usd"] += float(r.get("cost_usd") or 0)
    tgt["credits"] += float(r.get("credits") or 0)
    tgt["provider_wall_s"] += float(r.get("elapsed_s") or 0)
    tgt["calls"] += 1
for v in list(per_acct.values()) + [unattributed]:
    v["cost_usd"] = round(v["cost_usd"], 4)
    v["provider_wall_s"] = round(v["provider_wall_s"], 1)
    v["credits"] = round(v["credits"], 2)

# ---- scraping verdict
scrape = json.load(open("b1a_scrape_matrix.json"))
sv = {"urls_tried": 0, "exa_served": 0, "exa_missing": 0,
      "live_200": 0, "live_404": 0, "live_blocked_403_429": 0, "live_other": 0,
      "both_ok": 0, "exa_only": 0, "live_only": 0, "neither": 0, "detail": []}
for acct, blk in scrape.items():
    for p in blk["pages"]:
        sv["urls_tried"] += 1
        e_ok, l_code = p["exa_served"], p["live_http"]
        l_ok = l_code == 200
        sv["exa_served" if e_ok else "exa_missing"] += 1
        if l_ok:
            sv["live_200"] += 1
        elif l_code == 404:
            sv["live_404"] += 1
        elif l_code in (403, 429):
            sv["live_blocked_403_429"] += 1
        else:
            sv["live_other"] += 1
        key = ("both_ok" if (e_ok and l_ok) else "exa_only" if e_ok else
               "live_only" if l_ok else "neither")
        sv[key] += 1
        sv["detail"].append({"account": acct, "url": p["url"], "exa": e_ok,
                             "exa_chars": p["exa_chars"], "live_http": l_code,
                             "live_chars": p["live_chars"], "verdict": key})
# every other page fetch in the run (boards, careers, req pages, roots)
other_live = [r for r in B_LED if r.get("provider") in ("live_http", "ashby_public", "ats_public")]
sv["other_free_fetches"] = {
    "count": len(other_live),
    "http_200": sum(1 for r in other_live if r.get("http") == 200),
    "http_404": sum(1 for r in other_live if r.get("http") == 404),
    "http_403_429": sum(1 for r in other_live if r.get("http") in (403, 429)),
    "total_wall_s": round(sum(float(r.get("elapsed_s") or 0) for r in other_live), 1),
}

# ---- timing table
timing_rows = [{"agent": "A", **p} for p in A_TIM] + [{"agent": "B", **p} for p in B_TIM]

claims = json.load(open("claims_summary.json"))
out = {
    "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "agent_a": A, "agent_b": B,
    "combined": {
        "cost_usd": round(A["total_cost_usd"] + B["total_cost_usd"], 4),
        "credits": round(A["total_credits"] + B["total_credits"], 2),
        "provider_wall_s": round(A["total_wall_s"] + B["total_wall_s"], 1),
        "calls": A["total_calls"] + B["total_calls"],
    },
    "ceilings": {"cash_usd": 2.60, "credits": 50,
                 "cash_used_pct_b": round(100 * B["total_cost_usd"] / 2.60, 1),
                 "credits_used_pct_b": round(100 * B["total_credits"] / 50, 1)},
    "per_account_agent_b": per_acct,
    "unattributed_agent_b": unattributed,
    "scraping_verdict": sv,
    "timing_rows": timing_rows,
    "claims": claims,
}
json.dump(out, open("b5_tables.json", "w"), indent=2)

print("AGENT A:", json.dumps({k: A[k] for k in ("total_cost_usd", "total_credits",
                                                "total_wall_s", "total_calls")}))
print("AGENT B:", json.dumps({k: B[k] for k in ("total_cost_usd", "total_credits",
                                                "total_wall_s", "total_calls")}))
print("B by provider:", json.dumps(B["by_provider"], indent=1))
print("PER ACCOUNT (B):", json.dumps(per_acct, indent=1))
print("UNATTRIBUTED (B):", json.dumps(unattributed))
print("SCRAPING:", json.dumps({k: v for k, v in sv.items() if k != "detail"}, indent=1))
print("PHASE WALL (B, sum of recorded phases):",
      round(sum(p["seconds"] for p in B_TIM if not p["phase"].endswith("TOTAL")), 1))
