"""Phase 5a — sensitivity audit + every table the report needs. No paid calls."""

import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from roster import PEOPLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "claims_people.json")))["people"]
TRIAGE = json.load(open(os.path.join(HERE, "sweep_triage.json")))
SWEEP = json.load(open(os.path.join(HERE, "sweep_digest.json")))
MEDIA = json.load(open(os.path.join(HERE, "media_index.json")))
LEDGER = json.load(open(os.path.join(HERE, "cost_ledger.json")))
TIMING = json.load(open(os.path.join(HERE, "timing.json")))

# ---- sensitivity floor audit ------------------------------------------------
BANNED = {
    "health": r"\b(cancer|diagnos|illness|surgery|hospital|disabilit|therapy|depress|anxiety|medication|chronic)\b",
    "faith": r"\b(church|mosque|synagogue|temple|christian|muslim|jewish faith|hindu|buddhis|prayer|devout|faith-based)\b",
    "politics": r"\b(republican|democrat|labour party|conservative party|voted for|campaign donation|political party|activis[tm])\b",
    "sexuality": r"\b(gay|lesbian|lgbt|queer|transgender|coming out)\b",
    "family_tragedy": r"\b(passed away|died|funeral|bereave|divorce|widow|miscarriage)\b",
    "minors": r"\b(my (son|daughter|kids|children)|his son|her daughter|toddler|kindergarten|my child)\b",
    "union_legal": r"\b(trade union|lawsuit|indicted|convicted|arrested|criminal charge)\b",
}
ORIGIN = r"\b(fled|refugee|immigrat|emigrat|asylum|born in iran|left iran)\b"

CHARTER_CATS = ["background", "life_outside_work", "voice", "professional_identity",
                "unique_insight", "opener"]

SOURCE_TYPE_LABELS = [
    "linkedin_profile", "linkedin_post", "youtube", "podcast_dir", "podcast_site",
    "company_site", "personal_site_or_github", "substack_medium", "trade_press",
    "conference_event", "university_alumni", "social_x_bsky", "directory_aggregator",
]


def audit():
    hits = []
    for k, v in D.items():
        for c in v["claims"]:
            blob = (json.dumps(c.get("value")) + " " + (c.get("evidence_quote") or "")).lower()
            for cat, pat in BANNED.items():
                if re.search(pat, blob):
                    hits.append({"person": k, "field": c["field_key"], "category": cat,
                                 "snippet": blob[:200]})
        ui = json.dumps(v.get("unique_insight") or {}).lower()
        for cat, pat in BANNED.items():
            if re.search(pat, ui):
                hits.append({"person": k, "field": "unique_insight", "category": cat,
                             "snippet": ui[:200]})
    origin = []
    for k, v in D.items():
        blob = json.dumps(v).lower()
        for m in re.finditer(ORIGIN, blob):
            origin.append({"person": k, "term": m.group(0)})
    return hits, origin


def hooks_for(v):
    """A HOOK = a P1, outreach-safe claim in a person-revealing category."""
    out = []
    for c in v["claims"]:
        if c.get("priority") != "P1" or c.get("outreach_safe") is False:
            continue
        if c.get("charter_category") in ("background", "life_outside_work", "voice", "opener"):
            n = len(c["value"]) if isinstance(c["value"], list) else 1
            out.append((c["field_key"], min(n, 3)))
    return sum(n for _, n in out), out


def main():
    hits, origin = audit()
    tables = {}

    # 1. per-person scoreboard
    rows = []
    for p in PEOPLE:
        v = D[p["key"]]
        nhooks, _ = hooks_for(v)
        cats = Counter(c.get("charter_category") for c in v["claims"])
        ui = (v.get("unique_insight") or {}).get("text") or ""
        filled = sum(1 for c in CHARTER_CATS
                     if (cats.get(c, 0) > 0 or (c == "unique_insight" and ui
                                                and not ui.upper().startswith("NOT FOUND"))))
        rows.append({
            "person": p["name"], "key": p["key"], "title": p["title"], "company": p["company"],
            "depth_score": v["depth_score"], "claims": v["n_claims"], "p1": v["n_p1"],
            "hooks": nhooks, "charter_categories_filled": f"{filled}/6",
            "unique_insight_found": bool(ui) and not ui.upper().startswith("NOT FOUND"),
            "voice_rows": cats.get("voice", 0),
            "life_rows": cats.get("life_outside_work", 0),
            "background_rows": cats.get("background", 0),
            "not_found_count": len(v.get("not_found") or []),
        })
    tables["scoreboard"] = rows

    # 2. source-coverage matrix (which source TYPES yielded a named hit, per person)
    cov = {}
    for p in PEOPLE:
        t = TRIAGE[p["key"]]
        cov[p["key"]] = {st: (t["coverage"].get(st, 0)) for st in SOURCE_TYPE_LABELS}
    tables["source_coverage_matrix"] = cov
    yields = {st: sum(1 for k in cov if cov[k][st]) for st in SOURCE_TYPE_LABELS}
    tables["source_type_yield_across_10_people"] = dict(
        sorted(yields.items(), key=lambda x: -x[1]))

    # 3. angle productivity: which of the 12 search angles produced a NAMED strong hit
    angle_hits = defaultdict(int)
    angle_cost = defaultdict(float)
    for row in SWEEP:
        angle_cost[row["angle"]] += float(row.get("cost_usd") or 0)
        t = TRIAGE.get(row["person"]) or {}
        strong_urls = {r["url"] for r in t.get("strong_hits", [])}
        for r in row.get("results") or []:
            if r.get("url") in strong_urls:
                angle_hits[row["angle"]] += 1
                break
    tables["angle_productivity"] = sorted(
        [{"angle": a, "people_with_a_strong_hit": angle_hits.get(a, 0),
          "cost_usd": round(angle_cost[a], 3),
          "usd_per_person_served": round(angle_cost[a] / angle_hits[a], 4) if angle_hits.get(a) else None}
         for a in angle_cost], key=lambda r: -r["people_with_a_strong_hit"])

    # 4. money by provider / phase
    prov = defaultdict(lambda: {"calls": 0, "usd": 0.0, "seconds": 0.0})
    for e in LEDGER:
        pv = prov[e["provider"]]
        pv["calls"] += 1
        pv["usd"] += float(e.get("cost_usd") or 0)
        pv["seconds"] += float(e.get("elapsed_s") or 0)
    tables["by_provider"] = {k: {"calls": v["calls"], "usd": round(v["usd"], 4),
                                 "wire_seconds": round(v["seconds"], 1)}
                             for k, v in sorted(prov.items())}
    phase_of = {"p1_": "P1 sweep", "p1c_": "P1c targeted+linkedin", "p2": "P2 media",
                "yt_": "P2 media", "pod_": "P2 media", "rss_": "P2 media",
                "applelookup": "P2 media", "cap_": "P2 media", "live_": "P2 media",
                "p3_": "P3 deep-reasoning", "p4_": "P4 structuring", "p4b_": "P4b unique"}
    ph = defaultdict(lambda: {"calls": 0, "usd": 0.0})
    for e in LEDGER:
        lab = e.get("label") or ""
        name = next((v for k, v in phase_of.items() if lab.startswith(k)), "other")
        ph[name]["calls"] += 1
        ph[name]["usd"] += float(e.get("cost_usd") or 0)
    tables["by_phase_money"] = {k: {"calls": v["calls"], "usd": round(v["usd"], 4)}
                                for k, v in ph.items()}
    tables["by_phase_wallclock_s"] = {r["phase"]: r["seconds"] for r in TIMING["phases"]}
    tables["total_usd"] = round(sum(float(e.get("cost_usd") or 0) for e in LEDGER), 4)
    tables["total_credits"] = round(sum(float(e.get("credits") or 0) for e in LEDGER), 2)

    # 5. segment truth
    seg = {
        "people": len(rows),
        "avg_depth": round(sum(r["depth_score"] for r in rows) / len(rows), 1),
        "avg_hooks": round(sum(r["hooks"] for r in rows) / len(rows), 1),
        "insight_health_bar_hooks": 5,
        "people_at_or_above_bar": sum(1 for r in rows if r["hooks"] >= 5),
        "people_with_any_life_outside_work_row": sum(1 for r in rows if r["life_rows"]),
        "people_with_long_form_voice_media": sum(
            1 for p in PEOPLE if any(
                it["person"] == p["key"] and str(it.get("target_speaks", "")).startswith("YES")
                for it in MEDIA["items"])),
        "people_with_a_unique_insight": sum(1 for r in rows if r["unique_insight_found"]),
        "people_with_hometown": 0,
        "people_with_alma_mater": sum(
            1 for p in PEOPLE if any(c["field_key"] == "contact.facet.alma_mater"
                                     for c in D[p["key"]]["claims"])),
        "people_with_hobby_or_publication": sum(
            1 for p in PEOPLE if any(c["field_key"] in ("contact.facet.hobby",
                                                        "contact.facet.publications")
                                     for c in D[p["key"]]["claims"])),
    }
    for p in PEOPLE:
        nf = " ".join(D[p["key"]].get("not_found") or []).lower()
        if "hometown" not in nf:
            seg["people_with_hometown"] += 1
    tables["segment_truth"] = seg

    tables["sensitivity_audit"] = {
        "banned_category_hits": hits,
        "origin_mentions_requiring_the_not-an-outreach-hook_flag": origin,
        "verdict": ("CLEAN — no banned-category claim was recorded" if not hits
                    else f"{len(hits)} rows need review"),
    }

    json.dump(tables, open(os.path.join(HERE, "p5_tables.json"), "w"), indent=2)

    print("SENSITIVITY:", tables["sensitivity_audit"]["verdict"])
    if hits:
        for h in hits[:12]:
            print("   !!", h["person"], h["category"], h["field"], h["snippet"][:110])
    print("ORIGIN flags:", origin)
    print(f"\n{'person':<19}{'depth':>6}{'claims':>7}{'P1':>4}{'hooks':>6}{'cats':>6}  UI")
    for r in rows:
        print(f"{r['person']:<19}{r['depth_score']:>6}{r['claims']:>7}{r['p1']:>4}{r['hooks']:>6}"
              f"{r['charter_categories_filled']:>6}  {'Y' if r['unique_insight_found'] else 'n'}")
    print("\nSEGMENT:", json.dumps(seg, indent=1))
    print("\nMONEY:", json.dumps(tables["by_provider"], indent=1), "TOTAL", tables["total_usd"])
    print("\nANGLES:")
    for a in tables["angle_productivity"]:
        print(f"   {a['angle']:<26}{a['people_with_a_strong_hit']:>3}/10  ${a['cost_usd']:<7} "
              f"${a['usd_per_person_served'] or '-'}")
    print("\nSOURCE TYPE YIELD:", json.dumps(tables["source_type_yield_across_10_people"]))


if __name__ == "__main__":
    main()
