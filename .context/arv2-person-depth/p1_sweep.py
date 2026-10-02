"""Phase 1 — multi-source sweep. 11 recorded search angles x 10 people.

Every query is recorded VERBATIM alongside what it returned (sweep_digest.json), so the
source-coverage matrix in the report is derived from the wire, not from memory.
Cheap by construction: type=auto, numResults 8, contents.text 1500 chars (free tier).
"""

import concurrent.futures as cf
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402
from roster import PEOPLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

PODCAST_DOMAINS = ["podcasts.apple.com", "open.spotify.com", "podchaser.com",
                   "listennotes.com", "player.fm", "podbean.com", "buzzsprout.com"]
VIDEO_DOMAINS = ["youtube.com", "youtu.be", "vimeo.com"]
SOCIAL_DOMAINS = ["x.com", "twitter.com", "threads.net", "bsky.app", "reddit.com"]
WRITING_DOMAINS = ["substack.com", "medium.com", "dev.to", "hashnode.dev", "ghost.io"]


def angles(p):
    n = p["name"]
    alias = p["aliases"][0] if p["aliases"] else n
    co = p["company"]
    return [
        ("A1_podcast", f'"{n}" podcast interview guest episode {co}', None),
        ("A2_video", f'"{n}" {co} talk webinar video keynote', VIDEO_DOMAINS),
        ("A3_podcast_dirs", f'"{n}" {co}', PODCAST_DOMAINS),
        ("A4_authored", f'"{n}" article blog post author byline {co}', None),
        ("A5_writing_platforms", f'"{n}" {co} marketing security', WRITING_DOMAINS),
        ("A6_alumni", f'"{n}" university college alumni degree graduated studied', None),
        ("A7_awards", f'"{n}" award winner "40 under 40" top marketers recognition list', None),
        ("A8_personal_site", f'"{n}" personal website portfolio github about me', None),
        ("A9_social", f'"{alias}" {co}', SOCIAL_DOMAINS),
        ("A10_community", f'"{n}" volunteer board member advisor mentor nonprofit community', None),
        ("A11_local_hometown", f'"{n}" hometown grew up born raised local news feature', None),
    ]


MEDIA_PAT = re.compile(
    r"(youtube\.com/watch|youtu\.be/|youtube\.com/live/|vimeo\.com/\d|podcasts\.apple\.com|"
    r"open\.spotify\.com/episode|podchaser\.com/podcasts|listennotes\.com|player\.fm|"
    r"\.mp3|wistia|riverside\.fm|buzzsprout\.com|podbean\.com|libsyn\.com|megaphone\.fm|"
    r"transistor\.fm|simplecast\.com|captivate\.fm)", re.I)


def run_angle(p, angle_name, query, include_domains):
    payload = {
        "query": query,
        "type": "auto",
        "numResults": 8,
        "contents": {"text": {"maxCharacters": 1500}},
    }
    if include_domains:
        payload["includeDomains"] = include_domains
    label = f"p1_{p['key']}_{angle_name}"
    resp = C.exa(payload, label=label, est_usd=0.01, timeout=180)
    rows = []
    for r in (resp.get("results") or []):
        rows.append({
            "url": r.get("url"), "title": r.get("title"),
            "published": r.get("publishedDate"), "author": r.get("author"),
            "text_chars": len(r.get("text") or ""),
            "text_head": (r.get("text") or "")[:600],
        })
    return {
        "person": p["key"], "angle": angle_name, "query_verbatim": query,
        "include_domains": include_domains, "label": label,
        "http": resp.get("_http_status"), "elapsed_s": resp.get("_elapsed_s"),
        "cost_usd": (resp.get("costDollars") or {}).get("total"),
        "n_results": len(rows), "results": rows,
    }


def main():
    only = sys.argv[1:] or [p["key"] for p in PEOPLE]
    people = [p for p in PEOPLE if p["key"] in only]
    jobs = []
    for p in people:
        for a, q, dom in angles(p):
            jobs.append((p, a, q, dom))
    print(f"Phase 1: {len(people)} people x {len(jobs)//max(1,len(people))} angles = {len(jobs)} searches")
    t0 = time.time()
    out = []
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(run_angle, p, a, q, d): (p["key"], a) for (p, a, q, d) in jobs}
        for f in cf.as_completed(futs):
            key, a = futs[f]
            try:
                out.append(f.result())
            except Exception as e:  # noqa: BLE001
                print(f"  !! {key}/{a} FAILED: {type(e).__name__}: {e}", flush=True)
                out.append({"person": key, "angle": a, "error": f"{type(e).__name__}: {e}",
                            "n_results": 0, "results": []})
    el = time.time() - t0
    out.sort(key=lambda r: (r["person"], r["angle"]))
    json.dump(out, open(os.path.join(HERE, "sweep_digest.json"), "w"), indent=2)
    C.timing_record("P1_sweep", el, f"{len(jobs)} exa searches, 4 threads")

    # media candidates
    media = {}
    for row in out:
        for r in row.get("results") or []:
            u = r.get("url") or ""
            if MEDIA_PAT.search(u):
                media.setdefault(row["person"], {})
                media[row["person"]][u] = {
                    "url": u, "title": r.get("title"), "published": r.get("published"),
                    "found_by_angle": row["angle"],
                }
    json.dump({k: list(v.values()) for k, v in media.items()},
              open(os.path.join(HERE, "media_candidates.json"), "w"), indent=2)

    print(f"\nPhase 1 done in {el:.1f}s. spend=${C.total_spend()}")
    for p in people:
        rows = [r for r in out if r["person"] == p["key"]]
        yielded = [r["angle"] for r in rows if r.get("n_results")]
        print(f"  {p['key']:<20} angles_with_results={len(yielded)}/{len(rows)} "
              f"media_candidates={len(media.get(p['key'], {}))}")


if __name__ == "__main__":
    main()
