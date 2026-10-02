"""Z2b — Ashby posting API with the correct board slug (zafran-security, from the live apply URL)."""
import json, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

t0 = time.time(); out = {}
for slug in ["zafran-security", "zafran"]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    r = C.live_fetch(url, label=f"ashby_{slug}", accept="application/json")
    try:
        board = json.loads(r["text"])
    except Exception:
        board = {"_unparsed": r["text"][:400]}
    C.save_raw(f"z2b_ashby_{slug}", board)
    jobs = board.get("jobs") or []
    out[slug] = {"http": r["status"], "n_jobs": len(jobs),
                 "board_top_keys": sorted(board.keys()),
                 "job_field_names": sorted(jobs[0].keys()) if jobs else [],
                 "jobs": jobs}
    print(f"  slug={slug} http={r['status']} jobs={len(jobs)}")
    for j in jobs:
        print(f"    - {j.get('title')} | {j.get('department')}/{j.get('team')} | "
              f"{j.get('location')} | pub={j.get('publishedAt')} | listed={j.get('isListed')} "
              f"| remote={j.get('isRemote')}")
        print(f"      {j.get('jobUrl')}")
    if jobs:
        break
json.dump(out, open("z2b_ashby.json", "w"), indent=2)
C.timing_record("Z2b_ashby", time.time() - t0, "free ATS API")
print(f"\nZ2b {round(time.time()-t0,1)}s")
