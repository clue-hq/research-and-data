"""Z2 — free/cheap sources: Ashby live reqs (free ATS API), own-site reads, gap searches,
and media discovery for the Gemini layer."""
import json, re, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

t_all = time.time()
res = {}

# ---- 1. FREE: Ashby posting API (live req truth) ---------------------------
print("== Ashby live reqs (FREE) ==")
r = C.live_fetch("https://api.ashbyhq.com/posting-api/job-board/zafran?includeCompensation=true",
                 label="ashby_zafran", accept="application/json")
try:
    board = json.loads(r["text"])
except Exception:
    board = {"_unparsed": r["text"][:2000]}
C.save_raw("z2_ashby_zafran", board)
jobs = board.get("jobs") or []
res["ashby"] = {"http": r["status"], "n_jobs": len(jobs), "top_keys": sorted(board.keys()),
                "job_field_names": sorted(jobs[0].keys()) if jobs else [],
                "jobs": [{k: j.get(k) for k in
                          ("title", "department", "team", "location", "employmentType",
                           "publishedAt", "isListed", "isRemote", "jobUrl", "applyUrl",
                           "compensation", "secondaryLocations", "address")} for j in jobs]}
print(f"   jobs={len(jobs)}")
for j in res["ashby"]["jobs"]:
    print(f"   - {j['title']} | {j['department']}/{j['team']} | {j['location']} | pub={j['publishedAt']} | listed={j['isListed']}")

# ---- 2. own-site reads (Exa /contents, livecrawl) --------------------------
print("\n== own-site reads ==")
SITE = ["https://www.zafran.io/", "https://www.zafran.io/platform", "https://www.zafran.io/about",
        "https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai"]
own = C.exa_contents(SITE, label="z2_own_site", text_chars=12000, livecrawl="preferred")
res["own_site"] = [{"url": x.get("url"), "title": x.get("title"),
                    "chars": len(x.get("text") or "")} for x in (own.get("results") or [])]
for x in res["own_site"]:
    print(f"   {x['chars']:>6} chars  {x['url']}")

# ---- 3. gap searches (<=6) -------------------------------------------------
QUERIES = [
    ("media_nick", "Cocktail Chemistry YouTube channel Nick Fisher creator cocktail book", 6),
    ("media_sanaz", "Sanaz Yashar Zafran Security podcast interview episode audio", 6),
    ("rumour_cisco", "Zafran Security Cisco acquisition talks Calcalist report", 6),
    ("customers", "Zafran Security customer case study named enterprise deployment", 6),
    ("abm_stack", "Zafran Security marketing 6sense Demandbase HubSpot ABM intent platform", 6),
    ("compete", "Zafran Security vs Tenable Wiz exposure management competitive comparison 2026", 6),
]
res["searches"] = {}
for label, q, n in QUERIES:
    out = C.exa({"query": q, "type": "auto", "numResults": n,
                 "contents": {"text": {"maxCharacters": 2500}}}, label=f"z2_search_{label}")
    res["searches"][label] = {"query": q, "cost": (out.get("costDollars") or {}).get("total"),
                              "results": [{"url": x.get("url"), "title": x.get("title"),
                                           "published": x.get("publishedDate"),
                                           "text_head": (x.get("text") or "")[:600]}
                                          for x in (out.get("results") or [])]}
    print(f"   [{label}] {len(res['searches'][label]['results'])} results")
    for x in res["searches"][label]["results"][:6]:
        print(f"      - {x['title']} :: {x['url']}")

json.dump(res, open("z2_free.json", "w"), indent=2)
C.timing_record("Z2_free_sources", time.time() - t_all, "ashby + own site + 6 searches")
print(f"\nZ2 {round(time.time()-t_all,1)}s spend={C.total_spend()} credits={C.total_credits()}")
