"""H1 — the FREE typed hiring truth: Hotel Equities' four public ADP WorkforceNow career centres.

Pulls ALL pages of all four centres, then computes the Conduit-relevant view: the guest-facing
seats Conduit automates or relieves (front desk / guest services / night audit / front office),
GM openings (onboarding moments), by brand and geography, with days-open and 7/30-day velocity.

Free. Zero credits, zero cash. python3 stdlib only.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

CID = "30fbf914-a807-419c-b19e-409fa2c6a5f6"
BASE = ("https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/"
        "job-requisitions?cid=" + CID + "&ccId={cc}&locale=en_US&$top=50&$skip={skip}")
CENTRES = [
    ("9200396175623_2", "US management & sales"),
    ("9200402480447_2", "US hourly / property"),
    ("9200585439604_2", "Canada hourly"),
    ("9200585441819_2", "Canada management"),
]
TODAY = datetime(2026, 9, 22, tzinfo=timezone.utc)

# The seats Conduit automates or relieves (guest messaging, after-hours response, front office).
CONDUIT_SEATS = [
    ("guest_service", r"guest\s*service|guest\s*experience|guest\s*relation|guest\s*ambassador"),
    ("front_desk", r"front\s*desk|front\s*office|guest\s*service\s*agent|gsa\b|rooms?\s*controller"),
    ("night_audit", r"night\s*audit"),
    ("reservations", r"reservation"),
    ("pbx_communications", r"\bpbx\b|communications?\s*(agent|operator)|at[- ]your[- ]service"),
]
GM_RE = r"\bgeneral\s*manager\b|\bgm\b|assistant\s*general\s*manager|\bagm\b"
BRANDS = ["marriott", "hilton", "ihg", "holiday inn", "hampton", "courtyard", "residence inn",
          "fairfield", "springhill", "towneplace", "hyatt", "choice", "wyndham", "home2",
          "homewood", "embassy suites", "doubletree", "tru by", "element", "aloft", "ac hotel",
          "delta hotels", "moxy", "westin", "sheraton", "autograph", "tribute", "canopy",
          "curio", "tapestry", "staybridge", "candlewood", "avid", "even hotel", "kimpton",
          "crowne plaza", "postcard cabins", "springboard"]


def iso_days(d):
    if not d:
        return None
    try:
        dt = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (TODAY - dt).days
    except Exception:
        return None


def locs(req):
    out = []
    for L in (req.get("requisitionLocations") or []):
        nc = L.get("nameCode") or {}
        addr = L.get("address") or {}
        city = (addr.get("cityName") or "")
        state = ((addr.get("countrySubdivisionLevel1") or {}).get("codeValue")
                 or (addr.get("countrySubdivisionLevel1") or {}).get("shortName") or "")
        country = (addr.get("countryCode") or "")
        out.append({"short": nc.get("shortName"), "long": nc.get("longName"),
                    "city": city, "state": state, "country": country})
    return out


def pull_centre(cc, label):
    """All pages of one career centre. Also harvests meta.links LOCATION arguments,
    which carry the FULL property roster served by that centre (name, city, state)."""
    reqs, skip, total, props = [], 0, None, []
    while True:
        url = BASE.format(cc=cc, skip=skip)
        r = C.live_fetch(url, label=f"adp_{cc}_{skip}", accept="application/json",
                         timeout=45, save=False)
        try:
            body = json.loads(r["text"])
        except Exception:
            print(f"   !! unparsable page cc={cc} skip={skip}: {r['text'][:200]}")
            break
        C.save_raw(f"h1_adp_{cc}_skip{skip}", body)
        meta = body.get("meta") or {}
        total = meta.get("totalNumber") if total is None else total
        if not props:
            for lk in (meta.get("links") or []):
                if lk.get("schema") == "LOCATION":
                    props = [a.get("argumentValue") for a in (lk.get("payLoadArguments") or [])]
        page = body.get("jobRequisitions") or []
        reqs += page
        print(f"   cc={cc} skip={skip} got={len(page)} total={total} props={len(props)}")
        # WIRE FACT: the endpoint honours $skip but NOT $top — it returns ~19-20 rows per page
        # regardless. Advancing by 50 silently drops records (first pass got 72 of 143). Advance
        # by the page length actually returned.
        if not page:
            break
        skip += len(page)
        if total is not None and skip >= total:
            break
        if skip > 400:
            print("   !! runaway paging guard hit")
            break
    return total, reqs, props


t_all = time.time()
all_rows = []
centre_meta = {}
property_roster = []
for cc, label in CENTRES:
    print(f"== ADP centre {label} ({cc}) ==")
    total, reqs, props = pull_centre(cc, label)
    centre_meta[cc] = {"label": label, "total_reported": total, "pulled": len(reqs),
                       "properties_listed": len(props)}
    property_roster += [{"centre": label, "property": p} for p in props]
    for q in reqs:
        title = q.get("requisitionTitle") or ""
        post = q.get("postDate")
        L = locs(q)
        blob = " ".join([title] + [f"{x.get('short') or ''} {x.get('long') or ''}" for x in L]).lower()
        seats = [k for k, rx in CONDUIT_SEATS if re.search(rx, title, re.I)]
        brand = next((b for b in BRANDS if b in blob), None)
        all_rows.append({
            "centre": label, "ccId": cc,
            "id": q.get("itemID") or q.get("customFieldGroup", {}).get("stringFields", [{}])[0].get("itemID"),
            "title": title,
            "postDate": post,
            "days_open": iso_days(post),
            "locations": L,
            "location_short": "; ".join(x.get("short") or "" for x in L),
            "conduit_seat": seats,
            "is_conduit_seat": bool(seats),
            "is_gm": bool(re.search(GM_RE, title, re.I)),
            "brand_guess": brand,
            "work_level": ((q.get("workLevelCode") or {}).get("shortName")),
            "salary_range": next((s.get("stringValue") for s in
                                  ((q.get("customFieldGroup") or {}).get("stringFields") or [])
                                  if (s.get("nameCode") or {}).get("codeValue") == "SalaryRange"),
                                 None),
            "external_job_id": next((s.get("stringValue") for s in
                                     ((q.get("customFieldGroup") or {}).get("stringFields") or [])
                                     if (s.get("nameCode") or {}).get("codeValue") == "ExternalJobID"),
                                    None),
            "applicant_count": next((nf.get("numberValue") for nf in
                                     ((q.get("customFieldGroup") or {}).get("numberFields") or [])
                                     if (nf.get("categoryCode") or {}).get("codeValue")
                                     == "ApplicantCount"), None),
            "top_keys": sorted(q.keys()),
        })

n = len(all_rows)
seats = [r for r in all_rows if r["is_conduit_seat"]]
gms = [r for r in all_rows if r["is_gm"]]
fresh7 = [r for r in all_rows if (r["days_open"] is not None and r["days_open"] <= 7)]
fresh30 = [r for r in all_rows if (r["days_open"] is not None and r["days_open"] <= 30)]

by_seat = {}
for r in seats:
    for s in r["conduit_seat"]:
        by_seat.setdefault(s, []).append(r["title"])
by_state = {}
for r in all_rows:
    for L in r["locations"]:
        k = (L.get("state") or L.get("country") or "?")
        by_state[k] = by_state.get(k, 0) + 1
by_brand = {}
for r in all_rows:
    if r["brand_guess"]:
        by_brand[r["brand_guess"]] = by_brand.get(r["brand_guess"], 0) + 1

summary = {
    "pulled_at": TODAY.strftime("%Y-%m-%d"),
    "centres": centre_meta,
    "total_open_reqs": n,
    "conduit_seat_reqs": len(seats),
    "conduit_seat_share_pct": round(100.0 * len(seats) / n, 1) if n else 0,
    "conduit_seats_by_kind": {k: len(v) for k, v in by_seat.items()},
    "conduit_seat_titles": sorted({r["title"] for r in seats}),
    "gm_reqs": len(gms),
    "gm_titles": sorted({r["title"] for r in gms}),
    "posted_last_7_days": len(fresh7),
    "posted_last_30_days": len(fresh30),
    "oldest_open_days": max([r["days_open"] for r in all_rows if r["days_open"] is not None] or [0]),
    "median_days_open": sorted([r["days_open"] for r in all_rows if r["days_open"] is not None])[n // 2]
    if n else None,
    "by_state_or_country": dict(sorted(by_state.items(), key=lambda kv: -kv[1])),
    "by_brand_mentioned": dict(sorted(by_brand.items(), key=lambda kv: -kv[1])),
    "req_field_names": sorted({k for r in all_rows for k in r["top_keys"]}),
    "properties_in_location_filter": len({p["property"] for p in property_roster}),
    "no_job_description_text": ("The ADP public requisition object carries NO description field; "
                                "the per-requisition detail endpoint returns the same object. "
                                "Titles, locations, post dates and salary ranges are the whole "
                                "payload — verified by probing "
                                "/job-requisitions/<itemID> and <itemID>?$expand=all, both 200 "
                                "with identical bodies."),
}
json.dump({"summary": summary, "reqs": all_rows, "property_roster": property_roster},
          open("h1_adp.json", "w"), indent=2)

print("\n=== ADP SUMMARY ===")
print(json.dumps({k: v for k, v in summary.items() if k not in
                  ("conduit_seat_titles", "gm_titles", "req_field_names")}, indent=2)[:3000])
print("\nConduit-seat titles:")
for t in summary["conduit_seat_titles"]:
    print("   -", t)
print("\nGM titles:")
for t in summary["gm_titles"][:40]:
    print("   -", t)
C.timing_record("H1_adp_feed", time.time() - t_all, f"4 centres, {n} reqs, free")
print(f"\nH1 {round(time.time()-t_all,1)}s reqs={n} seats={len(seats)} spend={C.total_spend()}")
