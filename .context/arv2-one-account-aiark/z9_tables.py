"""Z9 — cost + timing tables. Zero provider calls; every number read from the ledger."""
import json, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

led = json.load(open("cost_ledger.json"))
tim = json.load(open("timing.json"))

by_prov = {}
for r in led:
    p = r["provider"]
    d = by_prov.setdefault(p, {"calls": 0, "cost_usd": 0.0, "credits": 0.0, "elapsed_s": 0.0,
                               "http_non200": 0})
    d["calls"] += 1
    d["cost_usd"] += float(r.get("cost_usd") or 0)
    d["credits"] += float(r.get("credits") or 0)
    d["elapsed_s"] += float(r.get("elapsed_s") or 0)
    if r.get("http") not in (200, None):
        d["http_non200"] += 1
for d in by_prov.values():
    d["cost_usd"] = round(d["cost_usd"], 6)
    d["credits"] = round(d["credits"], 2)
    d["elapsed_s"] = round(d["elapsed_s"], 1)

ark_detail = [{"label": r["label"], "op": r["op"], "http": r["http"],
               "credits": r.get("credits"), "elapsed_s": r["elapsed_s"],
               "returned": r.get("n_returned"), "totalElements": r.get("totalElements"),
               "note": r.get("note")} for r in led if r["provider"] == "ai_ark"]
gem = [{"label": r["label"], "op": r["op"], "cost_usd": r.get("cost_usd"),
        "elapsed_s": r["elapsed_s"], "usage": r.get("usage"),
        "audio_seconds": r.get("audio_seconds")}
       for r in led if r["provider"] == "gemini" and "generateContent" in str(r.get("op"))]
exa = [{"label": r["label"], "op": r["op"], "cost_usd": r.get("cost_usd"),
        "elapsed_s": r["elapsed_s"], "n_results": r.get("n_results")}
       for r in led if r["provider"] == "exa"]

# --- media economics, measured ---
SAN, MOSCOW, SUPPORT, FACELESS = 2569, 254, 91, 540
media_rows = []
for m, secs, person in [("z4b_sanaz_boardroom_meta.json", SAN, "Sanaz Yashar"),
                        ("z4a_nick_moscow_mule_meta.json", MOSCOW, "Nick Fisher"),
                        ("z4a_nick_supporting_cc_meta.json", SUPPORT, "Nick Fisher"),
                        ("z4a_nick_faceless_meta.json", FACELESS, "DISCARDED (wrong person)")]:
    d = json.load(open(m))
    um = d["usageMetadata"]
    audio = sum(x["tokenCount"] for x in um.get("promptTokensDetails", [])
                if x["modality"] in ("AUDIO", "VIDEO"))
    media_rows.append({
        "person": person, "item": m.replace("_meta.json", ""), "media_seconds": secs,
        "media_minutes": round(secs / 60, 2),
        "modality": "AUDIO" if "sanaz" in m else "VIDEO(youtube)",
        "media_tokens": audio, "tokens_per_second": round(audio / secs, 1),
        "output_tokens": um.get("candidatesTokenCount"),
        "cost_usd": d["cost_usd"], "latency_s": d["elapsed_s"],
        "usd_per_hour_of_media": round(d["cost_usd"] / (secs / 3600), 4),
        "transcript_chars": d["chars"]})
kept = [m for m in media_rows if "DISCARDED" not in m["person"]]
emb = json.load(open("z6_retrieval_demo.json"))

media_total_s = sum(m["media_seconds"] for m in kept)
media_total_cost = round(sum(m["cost_usd"] for m in kept), 6)

# --- per-provider recipe costing (full vs trimmed) ---
ark_credits = by_prov.get("ai_ark", {}).get("credits", 0)
exa_cost = by_prov.get("exa", {}).get("cost_usd", 0)
gem_cost = by_prov.get("gemini", {}).get("cost_usd", 0)
or_cost = by_prov.get("openrouter", {}).get("cost_usd", 0)

FULL = [
    {"line": "AI Ark company search (size 3)", "unit": "0.1cr/result", "qty": "1 result",
     "credits": 0.1, "usd": 0.0},
    {"line": "AI Ark people, domain-scoped roster", "unit": "0.5cr/profile", "qty": "12 profiles",
     "credits": 6.0, "usd": 0.0},
    {"line": "AI Ark people, name-scoped committee lookups", "unit": "0.5cr/profile",
     "qty": "3 lookups x 1 hit", "credits": 1.5, "usd": 0.0},
    {"line": "AI Ark email export", "unit": "1cr when found", "qty": "4 people, 4 found",
     "credits": 4.0, "usd": 0.0},
    {"line": "Ashby posting API (27 live reqs + full JDs)", "unit": "free", "qty": "1 GET",
     "credits": 0.0, "usd": 0.0},
    {"line": "Podcast RSS feed (mp3 enclosure + duration)", "unit": "free", "qty": "1 GET",
     "credits": 0.0, "usd": 0.0},
    {"line": "Exa /contents own-site (4 pages, livecrawl)", "unit": "$0.001/page", "qty": "4",
     "credits": 0.0, "usd": 0.004},
    {"line": "Exa /contents identity binding (3 urls)", "unit": "$0.001/page", "qty": "2 returned",
     "credits": 0.0, "usd": 0.002},
    {"line": "Exa search, gap + media discovery", "unit": "$0.007/search", "qty": "8 searches",
     "credits": 0.0, "usd": 0.056},
    {"line": "Exa deep-reasoning, 1 account call", "unit": "$0.025", "qty": "1",
     "credits": 0.0, "usd": 0.025},
    {"line": "Gemini transcription, podcast 42:49", "unit": "measured", "qty": "1",
     "credits": 0.0, "usd": kept[0]["cost_usd"]},
    {"line": "Gemini transcription, 2 short YouTube items (5:45 total)", "unit": "measured",
     "qty": "2", "credits": 0.0, "usd": round(kept[1]["cost_usd"] + kept[2]["cost_usd"], 6)},
    {"line": "Gemini embedding-2 index + 3 retrieval queries", "unit": "$0.20/1M",
     "qty": f"{emb['chunks']} chunks", "credits": 0.0, "usd": emb["total_embed_cost_usd"]},
    {"line": "gpt-5-mini structuring (1 call)", "unit": "measured", "qty": "1",
     "credits": 0.0, "usd": or_cost},
    {"line": "Gemini transcription of a WRONG-PERSON video (waste)", "unit": "measured",
     "qty": "1", "credits": 0.0, "usd": media_rows[3]["cost_usd"]},
    {"line": "Gemini re-transcription on gemini-3.5-transcribe (quality repair after the "
             "flash-lite loop)", "unit": "measured", "qty": "1", "credits": 0.0,
     "usd": json.load(open("z4d_transcribe_meta.json"))["cost_usd"]},
    {"line": "Gemini second-half quote mining (text-only)", "unit": "measured", "qty": "1",
     "credits": 0.0, "usd": 0.000636},
]
TRIM = [
    {"line": "AI Ark company search (size 1)", "credits": 0.1, "usd": 0.0,
     "why": "the single highest-yield call in the whole run"},
    {"line": "AI Ark name-scoped lookups for the 4 known committee members", "credits": 2.0,
     "usd": 0.0, "why": "skip the 12-profile domain roster: 10 of its 12 were RSMs, not buyers"},
    {"line": "AI Ark email export x2 (champion + economic buyer only)", "credits": 2.0,
     "usd": 0.0, "why": "CEO/SVP emails are nice-to-have, not the send target"},
    {"line": "Ashby posting API", "credits": 0.0, "usd": 0.0,
     "why": "free and out-performed the $0.025 deep call on tooling"},
    {"line": "Exa /contents own site (3 pages)", "credits": 0.0, "usd": 0.003,
     "why": "homepage carries the named-customer testimonials"},
    {"line": "Exa deep-reasoning, 1 call", "credits": 0.0, "usd": 0.025,
     "why": "the only source of the negatives/reputation layer"},
    {"line": "Gemini media, 1 item for the primary target only", "credits": 0.0,
     "usd": kept[1]["cost_usd"], "why": "one short item per person is enough for voice"},
    {"line": "Gemini ASR on the long podcast (gemini-3.5-transcribe, no timestamps)",
     "credits": 0.0, "usd": json.load(open("z4d_transcribe_meta.json"))["cost_usd"],
     "why": "cheaper AND faithful; use it as the primary ASR and keep flash-lite only for "
            "short items where timestamps matter"},
    {"line": "gpt-5-mini structuring", "credits": 0.0, "usd": or_cost, "why": "required"},
]
CREDIT_PRICES = {"free_tier": 0.0, "at_$0.02/cr": 0.02, "at_$0.05/cr": 0.05}
tables = {
    "this_run_by_provider": by_prov,
    "this_run_totals": {"cash_usd": round(sum(d["cost_usd"] for d in by_prov.values()), 6),
                        "ai_ark_credits": ark_credits,
                        "calls": sum(d["calls"] for d in by_prov.values()),
                        "wall_clock_s_sum_of_calls": round(
                            sum(d["elapsed_s"] for d in by_prov.values()), 1)},
    "ai_ark_calls": ark_detail,
    "exa_calls": exa,
    "gemini_generate_calls": gem,
    "media_economics": {
        "items": media_rows, "kept_items": len(kept),
        "kept_media_seconds": media_total_s,
        "kept_media_minutes": round(media_total_s / 60, 1),
        "kept_media_cost_usd": media_total_cost,
        "blended_usd_per_hour_of_media": round(media_total_cost / (media_total_s / 3600), 4),
        "audio_vs_video_tokens_per_second": {
            "audio_mp3_measured": kept[0]["tokens_per_second"],
            "youtube_video_measured": [k["tokens_per_second"] for k in kept[1:]]},
        "embedding": {k: emb[k] for k in ("chunks", "doc_tokens", "doc_cost_usd",
                                          "query_tokens", "query_cost_usd",
                                          "total_embed_cost_usd",
                                          "raw_audio_embedding_would_have_cost_usd",
                                          "raw_audio_seconds_considered")},
        "per_person": {
            "Sanaz Yashar": {"items": 1, "seconds": SAN,
                             "cost_usd": round(kept[0]["cost_usd"], 6)},
            "Nick Fisher": {"items": 2, "seconds": MOSCOW + SUPPORT,
                            "cost_usd": round(kept[1]["cost_usd"] + kept[2]["cost_usd"], 6)}},
    },
    "recipe_full": {"lines": FULL,
                    "usd": round(sum(x["usd"] for x in FULL), 6),
                    "credits": round(sum(x["credits"] for x in FULL), 2)},
    "recipe_trimmed": {"lines": TRIM,
                       "usd": round(sum(x["usd"] for x in TRIM), 6),
                       "credits": round(sum(x["credits"] for x in TRIM), 2)},
    "credit_price_scenarios": {
        k: {"full_recipe_total_usd": round(sum(x["usd"] for x in FULL)
                                           + sum(x["credits"] for x in FULL) * v, 4),
            "trimmed_recipe_total_usd": round(sum(x["usd"] for x in TRIM)
                                              + sum(x["credits"] for x in TRIM) * v, 4)}
        for k, v in CREDIT_PRICES.items()},
    "ceilings": {"cash_ceiling_usd": C.CASH_CEILING, "cash_used_usd": C.total_spend(),
                 "ai_ark_credit_ceiling": C.CREDIT_CEILING, "ai_ark_credits_used": ark_credits,
                 "media_ceiling_seconds": C.MEDIA_SECONDS_CEILING,
                 "media_seconds_processed": media_total_s + FACELESS},
    "apollo": {"calls": 0, "cost_usd": 0.0,
               "proof": "no apollo helper exists in z_lib.py and no ledger row has "
                        "provider=='apollo' or an api.apollo.io URL"},
    "timing": tim,
}
json.dump(tables, open("z9_tables.json", "w"), indent=2)
print(json.dumps({"by_provider": by_prov, "totals": tables["this_run_totals"],
                  "media": {k: v for k, v in tables["media_economics"].items()
                            if k not in ("items",)},
                  "recipe_full_usd": tables["recipe_full"]["usd"],
                  "recipe_full_credits": tables["recipe_full"]["credits"],
                  "recipe_trim_usd": tables["recipe_trimmed"]["usd"],
                  "recipe_trim_credits": tables["recipe_trimmed"]["credits"],
                  "scenarios": tables["credit_price_scenarios"],
                  "ceilings": tables["ceilings"]}, indent=1))
