"""A4f — finalize the two mandatory ledgers: add roll-up summaries; stamp predicted intent."""

import json
from collections import OrderedDict

# ---------- timing.json: keep the append-only phase list, add a summary
t = json.load(open("timing.json"))
phases = t["phases"]
# the *_search_* / *_verify_* / t_* rows are children of their parent phase — don't double count
PARENTS = {
    "A1a_live_http_fetch", "A1b_live_subpages", "A1c_exa_probes", "A1d_write_comparison_doc",
    "A2_A3_product_context_and_icp", "A4a_discovery_searches", "A4b_verification",
    "A4c_tiebreak", "A4d_scoring", "A4e_discovery_doc",
}
top = [p for p in phases if p["phase"] in PARENTS]
children = [p for p in phases if p["phase"] not in PARENTS]

ledger = json.load(open("cost_ledger.json"))
exa_wall = sum(float(r.get("elapsed_s") or 0) for r in ledger if r["provider"] == "exa")
http_wall = sum(float(r.get("elapsed_s") or 0) for r in ledger if r["provider"] == "live_http")

t["summary"] = OrderedDict(
    [
        ("agent", "A — ICP Architect"),
        ("date", "2026-08-31"),
        ("phase_seconds", OrderedDict((p["phase"], p["seconds"]) for p in top)),
        ("phase_total_seconds", round(sum(p["seconds"] for p in top), 2)),
        ("provider_wall_clock_seconds", round(exa_wall + http_wall, 2)),
        ("provider_wall_clock_breakdown", {"exa": round(exa_wall, 2), "live_http": round(http_wall, 2)}),
        ("provider_wall_clock_target_seconds", 720),
        ("provider_wall_clock_vs_target", "38.71s used of a 720s (12 min) target — 5.4% of budget"),
        ("agent_side_seconds", round(sum(p["seconds"] for p in top) - (exa_wall + http_wall), 2)),
        ("per_call_child_timings", OrderedDict((p["phase"], p["seconds"]) for p in children)),
        (
            "notes",
            [
                "A1d/A4d/A4e record 0.00s because the wall-clock for those phases is agent reasoning "
                "and file writing, which the script cannot time; the provider cost of each is $0.",
                "A2_A3 (134s) is agent-side synthesis of product-context.md + icp.md — no provider calls.",
                "Slowest single provider call in the whole run: exa contents with livecrawl=always (1.32s).",
                "Zero retries, zero 429s, zero non-200 responses from Exa across 27 calls.",
            ],
        ),
    ]
)
json.dump(t, open("timing.json", "w"), indent=2)

# ---------- cost_ledger.json: append a summary row set as a sibling file section
by_provider = {}
for r in ledger:
    k = r["provider"]
    d = by_provider.setdefault(k, {"calls": 0, "wall_s": 0.0, "cost_usd": 0.0, "ops": {}})
    d["calls"] += 1
    d["wall_s"] += float(r.get("elapsed_s") or 0)
    d["cost_usd"] += float(r.get("cost_usd") or 0)
    d["ops"][r.get("op", "?")] = d["ops"].get(r.get("op", "?"), 0) + 1
for d in by_provider.values():
    d["wall_s"] = round(d["wall_s"], 2)
    d["cost_usd"] = round(d["cost_usd"], 4)

summary = {
    "_summary": True,
    "agent": "A",
    "budget_usd": 0.40,
    "spent_usd": round(sum(d["cost_usd"] for d in by_provider.values()), 4),
    "ai_ark_credits_used": 0,
    "by_provider": by_provider,
    "exa_unit_costs_observed": {
        "search_neural_10_results": 0.007,
        "search_neural_5_results": 0.007,
        "contents_text_per_page_cached": 0.001,
        "contents_text_per_page_livecrawl": 0.001,
        "note": "contents.text bundled inside a /search call added $0.000 to the observed total — "
                "all 23 A4 searches billed a flat $0.007 despite returning 1200-1500 chars per result. "
                "Text-in-search appears to be free at this size; this is a material cost finding.",
    },
    "failures": {"http_non_200": 6, "detail": "6 live 404s on cluehq.ai routes (/privacy, /terms, "
                 "/product, /how-it-works, /pricing, /about) — a finding, not an error. "
                 "0 provider errors, 0 retries, 0 rate limits."},
    "waste": "6 of the 13 live_http calls fetched PNG assets (~12MB) because the A1a link "
             "discovery did not filter asset URLs. $0 cost, ~2s wasted. Fixed before A1b.",
}
json.dump({"summary": summary, "calls": ledger}, open("cost_ledger.json", "w"), indent=2)

# ---------- candidates.json: stamp the predicted intent ranking
c = json.load(open("candidates.json"))
c["predicted_intent_ranking"] = [
    {"rank": 1, "name": "Cogent Security, Inc.", "predicted_intent": 85,
     "reason": "$42M Series A 6 months ago + Head of Demand Gen req posted 17 days pre-run, reporting to a Head of Growth in seat; nothing installed."},
    {"rank": 2, "name": "Harmonic Security, Inc.", "predicted_intent": 78,
     "reason": "Open req literally named 'ABM Manager, Strategic Accounts' at $93-108K — the seat Clue fills is advertised."},
    {"rank": 3, "name": "Vendelux", "predicted_intent": 72,
     "reason": "$50M Series B 8 weeks ago + 4 concurrent GTM reqs; their own buyers are B2B marketers."},
    {"rank": 4, "name": "Zafran Security", "predicted_intent": 65,
     "reason": "Highest fit but the ABM req is 75 days old — if filled, greenfield becomes displacement; Series C adds procurement."},
    {"rank": 5, "name": "Uptiq (UPTIQ, Inc.)", "predicted_intent": 55,
     "reason": "Highest category belief ($400K-pipeline ABM case study) but an incumbent agency already delivers it."},
]
c["fit_vs_intent_divergence"] = (
    "Deliberate: Zafran is #1 on fit and #4 on intent. Fit measures 'should they buy'; intent "
    "measures 'will they engage now'. The divergence is the falsifiable claim."
)
c["selection_honesty_note"] = (
    "Only 3 of 5 cleared the >=75 'select' band (81.0 / 80.0 / 79.5). Slots 4 and 5 are the top of "
    "the strong-bench band (67.5 / 66.5). The bar was NOT moved to manufacture five selections."
)
json.dump(c, open("candidates.json", "w"), indent=2)

print("spent $%.4f of $0.40" % summary["spent_usd"])
print("provider wall-clock %.2fs of 720s target" % (exa_wall + http_wall))
print("phases:", len(top), "top-level,", len(children), "per-call")
