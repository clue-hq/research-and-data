"""H17 — the cost and timing tables, computed from the real ledger. Zero provider calls."""
import json
import os
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

RUN_START_EPOCH = 1790058847  # 2026-09-22T06:34:07Z, recorded before the first call
rows = json.load(open(C.LEDGER_PATH))
timing = json.load(open(C.TIMING_PATH))
media = json.load(open("media_index.json"))
embed = json.load(open("h13_retrieval_demo.json"))
claims = json.load(open("claims_hotelequities.json"))

# ------------------------------------------------------- per provider ------
prov = {}
for r in rows:
    p = r.get("provider")
    d = prov.setdefault(p, {"calls": 0, "cash": 0.0, "credits": 0.0, "seconds": 0.0,
                            "non_200": 0, "labels": []})
    d["calls"] += 1
    d["cash"] += float(r.get("cost_usd") or 0)
    d["credits"] += float(r.get("credits") or 0)
    d["seconds"] += float(r.get("elapsed_s") or 0)
    if r.get("http") and int(r["http"]) != 200:
        d["non_200"] += 1
for p, d in prov.items():
    d["cash"] = round(d["cash"], 6)
    d["credits"] = round(d["credits"], 2)
    d["seconds"] = round(d["seconds"], 1)
    d["avg_latency_s"] = round(d["seconds"] / d["calls"], 2) if d["calls"] else 0

# -------------------------------------------- per-call latency by op -------
by_op = {}
for r in rows:
    k = f"{r.get('provider')} :: {str(r.get('op'))[:52]}"
    e = by_op.setdefault(k, {"n": 0, "total_s": 0.0, "max_s": 0.0, "cash": 0.0})
    e["n"] += 1
    e["total_s"] += float(r.get("elapsed_s") or 0)
    e["max_s"] = max(e["max_s"], float(r.get("elapsed_s") or 0))
    e["cash"] += float(r.get("cost_usd") or 0)
for k, e in by_op.items():
    e["avg_s"] = round(e["total_s"] / e["n"], 2)
    e["total_s"] = round(e["total_s"], 1)
    e["cash"] = round(e["cash"], 5)

total_cash = round(sum(d["cash"] for d in prov.values()), 6)
total_credits = round(sum(d["credits"] for d in prov.values()), 2)

# ------------------------------------------------------- full recipe -------
def cash_for(pred):
    return round(sum(float(r.get("cost_usd") or 0) for r in rows if pred(r)), 6)


def n_for(pred):
    return sum(1 for r in rows if pred(r))


def lbl(r):
    return r.get("label") or ""


full = [
    {"item": "ADP WorkforceNow public feed — 4 career centres, all pages",
     "unit": "free", "qty": n_for(lambda r: lbl(r).startswith("adp_")),
     "credits": 0, "cash": 0.0},
    {"item": "AI Ark company object", "unit": "0.1 cr/company returned", "qty": 1,
     "credits": 0.1, "cash": 0.0},
    {"item": "AI Ark people, name-scoped + domain-scoped (the committee)",
     "unit": "0.5 cr/profile returned", "qty": 6, "credits": 3.0, "cash": 0.0},
    {"item": "AI Ark email export", "unit": "1 cr when found", "qty": "5 asked, 4 found",
     "credits": 4.0, "cash": 0.0},
    {"item": "Own-site direct fetches (all hung, 20s timeout each)", "unit": "free",
     "qty": n_for(lambda r: lbl(r).startswith("h2_direct")), "credits": 0, "cash": 0.0},
    {"item": "Exa /contents — own site, committee pages, key primary pages",
     "unit": "~$0.001/page", "qty": n_for(lambda r: r.get("op", "").startswith("contents")),
     "credits": 0, "cash": cash_for(lambda r: str(r.get("op", "")).startswith("contents"))},
    {"item": "Exa /search — committee discovery + gap searches", "unit": "$0.007/search",
     "qty": n_for(lambda r: lbl(r).startswith(("h4_search", "h7_"))),
     "credits": 0,
     "cash": cash_for(lambda r: lbl(r).startswith(("h4_search", "h7_")))},
    {"item": "Exa deep-reasoning — ONE account call", "unit": "$0.03/call", "qty": 1,
     "credits": 0, "cash": cash_for(lambda r: lbl(r).startswith("h5_deep"))},
    {"item": "Exa deep-reasoning — 5 per-person calls", "unit": "~$0.025/call", "qty": 5,
     "credits": 0, "cash": cash_for(lambda r: lbl(r).startswith("h11_person"))},
    {"item": "Podcast RSS + 5 MP3 downloads", "unit": "free",
     "qty": n_for(lambda r: lbl(r).startswith(("h8_", "h8b_", "h10_mp3"))),
     "credits": 0, "cash": 0.0},
    {"item": "Gemini transcription — 5 episodes, two models each (69 min of audio)",
     "unit": "measured", "qty": 10, "credits": 0,
     "cash": round(media["summary"]["total_cost_usd"], 6)},
    {"item": "Gemini embedding-2 index + 4 retrieval queries", "unit": "$0.20/1M",
     "qty": embed["chunks"] + len(embed["queries"]), "credits": 0,
     "cash": embed["total_embed_cost_usd"]},
    {"item": "gpt-5-mini structuring — 6 calls, one subject each", "unit": "measured", "qty": 6,
     "credits": 0, "cash": cash_for(lambda r: r.get("provider") == "openrouter")},
]
full_cash = round(sum(float(x["cash"]) for x in full), 6)
full_credits = round(sum(float(x["credits"]) for x in full), 2)

trimmed = [
    {"item": "ADP WorkforceNow feed (all four centres)", "credits": 0, "cash": 0.0,
     "why": "free, typed, and it is the P1 pain signal — never cut"},
    {"item": "AI Ark company object", "credits": 0.1, "cash": 0.0,
     "why": "highest yield per credit in the run; the only source of the SynXis fingerprint"},
    {"item": "AI Ark name-scoped lookups x 4 (sponsor, buyer, champion, evaluator)",
     "credits": 2.0, "cash": 0.0,
     "why": "employer re-confirmation + LinkedIn locator; the divisional and adjacent seats can "
            "wait for a second call"},
    {"item": "AI Ark email export x 3", "credits": 3.0, "cash": 0.0,
     "why": "sponsor, champion and evaluator are the send targets"},
    {"item": "Exa /contents — 6 primary pages (team, HE Labs, ITR, the two appointment posts)",
     "credits": 0, "cash": 0.006,
     "why": "these six pages carry the committee, the buying process and the money signal"},
    {"item": "Exa /search x 4 (committee, technology seat, ITR, negatives)", "credits": 0,
     "cash": 0.028, "why": "four narrow questions beat ten broad ones"},
    {"item": "Exa deep-reasoning — 1 account call", "credits": 0, "cash": 0.03,
     "why": "the only source of the reputation/negatives sweep"},
    {"item": "Exa deep-reasoning — 2 person calls (sponsor + evaluator)", "credits": 0,
     "cash": 0.05, "why": "the CEO and the IT chief are the two whose words change the email"},
    {"item": "Gemini transcription — 2 episodes, two models (21 min)", "credits": 0,
     "cash": 0.023, "why": "one on-topic episode per key voice is enough"},
    {"item": "Gemini embedding index + queries", "credits": 0, "cash": 0.0043,
     "why": "essentially free once the text exists"},
    {"item": "gpt-5-mini structuring x 3 (account + 2 people)", "credits": 0, "cash": 0.028,
     "why": "required"},
]
trim_cash = round(sum(float(x["cash"]) for x in trimmed), 6)
trim_credits = round(sum(float(x["credits"]) for x in trimmed), 2)

# ------------------------------------------------- per-person media --------
per_person = {}
for it in media["items"]:
    d = per_person.setdefault(it["person"], {"items": 0, "seconds": 0, "cash": 0.0})
    d["items"] += 1
    d["seconds"] += it["duration_seconds"]
    d["cash"] += it["total_cost_usd"]
for p, d in per_person.items():
    d["cash"] = round(d["cash"], 6)
    d["minutes"] = round(d["seconds"] / 60, 1)
    d["cost_per_hour"] = round(d["cash"] / (d["seconds"] / 3600), 4)

wall = round(time.time() - RUN_START_EPOCH, 1)
phases = timing.get("phases", [])
phase_total = round(sum(p["seconds"] for p in phases), 1)

tables = {
    "run": {
        "client": "Conduit (conduit.ai)", "account": "Hotel Equities (hotelequities.com)",
        "date": "2026-09-22",
        "run_started_utc": "2026-09-22T06:34:07Z",
        "total_wall_clock_seconds": wall,
        "total_wall_clock_hms": f"{int(wall//3600)}h {int((wall%3600)//60)}m {int(wall%60)}s",
        "sum_of_phase_seconds": phase_total,
        "parallelism_factor": round(phase_total / wall, 2) if wall else None,
        "total_cash_usd": total_cash, "cash_ceiling_usd": C.CASH_CEILING,
        "cash_ceiling_used_pct": round(100 * total_cash / C.CASH_CEILING, 1),
        "ai_ark_credits_actual": total_credits, "credit_ceiling": C.CREDIT_CEILING,
        "credit_ceiling_used_pct": round(100 * total_credits / C.CREDIT_CEILING, 1),
        "media_seconds": media["summary"]["total_media_seconds"],
        "media_ceiling_used_pct": media["summary"]["ceiling_used_pct"],
        "total_calls": len(rows),
        "apollo_calls": sum(1 for r in rows if "apollo" in str(r).lower()),
        "firecrawl_calls": sum(1 for r in rows if "firecrawl" in str(r).lower()),
        "ceilings_hit": [],
        "claims": claims["totals"]["claims"],
    },
    "per_provider": prov,
    "per_op_latency": dict(sorted(by_op.items(), key=lambda kv: -kv[1]["total_s"])),
    "full_recipe": {"lines": full, "total_credits": full_credits, "total_cash_usd": full_cash},
    "trimmed_recipe": {"lines": trimmed, "total_credits": trim_credits,
                       "total_cash_usd": trim_cash},
    "credit_price_scenarios": [
        {"credit_price_usd": 0.0, "label": "free tier (today)",
         "full_per_account": full_cash, "trimmed_per_account": trim_cash,
         "trimmed_x1000": round(trim_cash * 1000, 2)},
        {"credit_price_usd": 0.02, "label": "$0.02/credit",
         "full_per_account": round(full_cash + full_credits * 0.02, 4),
         "trimmed_per_account": round(trim_cash + trim_credits * 0.02, 4),
         "trimmed_x1000": round((trim_cash + trim_credits * 0.02) * 1000, 2)},
        {"credit_price_usd": 0.05, "label": "$0.05/credit",
         "full_per_account": round(full_cash + full_credits * 0.05, 4),
         "trimmed_per_account": round(trim_cash + trim_credits * 0.05, 4),
         "trimmed_x1000": round((trim_cash + trim_credits * 0.05) * 1000, 2)},
    ],
    "per_person_media": per_person,
    "media_items": media["items"],
    "embedding": {k: v for k, v in embed.items() if k != "queries"},
    "phases": sorted(phases, key=lambda p: -p["seconds"]),
}
json.dump(tables, open("h17_tables.json", "w"), indent=2)
print(json.dumps(tables["run"], indent=2))
print("\nper provider:")
for p, d in sorted(prov.items(), key=lambda kv: -kv[1]["cash"]):
    print(f"  {p:14s} calls={d['calls']:>3} cash=${d['cash']:<10} credits={d['credits']:<6} "
          f"in-call={d['seconds']:>7}s avg={d['avg_latency_s']}s non200={d['non_200']}")
print(f"\nFULL    {full_credits} cr  ${full_cash}")
print(f"TRIMMED {trim_credits} cr  ${trim_cash}")
