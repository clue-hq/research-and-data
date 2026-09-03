"""Phase 1b — triage the sweep. Separates results that actually name the target from noise,
builds the per-person source-coverage matrix, and shortlists media items for Phase 2.

Nothing here spends money. It reads sweep_digest.json (raw wire) only.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from roster import BY_KEY, PEOPLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = json.load(open(os.path.join(HERE, "sweep_digest.json")))

MEDIA_PAT = re.compile(
    r"(youtube\.com/watch|youtu\.be/|youtube\.com/live/|vimeo\.com/\d|podcasts\.apple\.com|"
    r"open\.spotify\.com/episode|podchaser\.com/podcasts|listennotes\.com|player\.fm|"
    r"\.mp3|wistia|riverside\.fm|buzzsprout\.com|podbean\.com|libsyn\.com|megaphone\.fm|"
    r"transistor\.fm|simplecast\.com|captivate\.fm|music\.youtube\.com)", re.I)
WALLED_PAT = re.compile(r"(linkedin\.com/(posts|feed|video)|x\.com/\w+/status|twitter\.com/\w+/status)", re.I)

SOURCE_TYPES = {
    "linkedin_profile": re.compile(r"linkedin\.com/in/", re.I),
    "linkedin_post": re.compile(r"linkedin\.com/posts/", re.I),
    "youtube": re.compile(r"(youtube\.com|youtu\.be)", re.I),
    "podcast_dir": re.compile(r"(podcasts\.apple\.com|open\.spotify\.com|podchaser|listennotes|player\.fm)", re.I),
    "podcast_site": re.compile(r"(buzzsprout|podbean|libsyn|megaphone|transistor\.fm|simplecast|captivate\.fm|\.mp3)", re.I),
    "company_site": None,          # filled per person
    "personal_site_or_github": re.compile(r"(github\.com|github\.io|\.me/|about\.me|notion\.site|carrd\.co)", re.I),
    "substack_medium": re.compile(r"(substack\.com|medium\.com|dev\.to|hashnode)", re.I),
    "trade_press": re.compile(r"(techcrunch|venturebeat|forbes|businessinsider|axios|zdnet|darkreading|"
                              r"securityweek|infosecurity|scmagazine|helpnetsecurity|cybernews|"
                              r"calcalist|ctech|geektime|thehackernews|siliconangle|crn\.com|"
                              r"martechseries|demandgenreport|prnewswire|businesswire)", re.I),
    "conference_event": re.compile(r"(rsaconference|blackhat|defcon|sched\.com|eventbrite|hopin|"
                                   r"sessionize|conference|summit|\.events?/)", re.I),
    "university_alumni": re.compile(r"(\.edu|alumni)", re.I),
    "social_x_bsky": re.compile(r"(x\.com|twitter\.com|bsky\.app|threads\.net|reddit\.com)", re.I),
    "directory_aggregator": re.compile(r"(rocketreach|zoominfo|apollo\.io|signalhire|lusha|contactout|"
                                       r"crunchbase|pitchbook|leadiq|clay\.com|theorg\.com|"
                                       r"f6s\.com|tracxn)", re.I),
}


def name_variants(p):
    v = [p["name"]] + list(p["aliases"])
    first = p["name"].split()[0]
    last = p["name"].split()[-1]
    v += [f"{first} {last}"]
    return sorted({x.lower() for x in v if x})


def hits_name(text, variants):
    t = (text or "").lower()
    return any(v in t for v in variants)


def main():
    out = {}
    media_index = {}
    for p in PEOPLE:
        key = p["key"]
        variants = name_variants(p)
        rows = [r for r in SWEEP if r["person"] == key]
        seen = {}
        coverage = {st: 0 for st in SOURCE_TYPES}
        coverage["company_site"] = 0
        for row in rows:
            for r in row.get("results") or []:
                u = r.get("url") or ""
                if not u:
                    continue
                title = r.get("title") or ""
                body = r.get("text_head") or ""
                named = hits_name(title, variants) or hits_name(body, variants)
                co = p["company"].split()[0].lower() in (title + body).lower() \
                    or p["domain"].split(".")[0].lower() in (title + body + u).lower()
                rec = seen.setdefault(u, {
                    "url": u, "title": title, "published": r.get("published"),
                    "author": r.get("author"), "angles": [], "named": named,
                    "company_mentioned": co, "text_head": body[:400],
                })
                rec["named"] = rec["named"] or named
                rec["company_mentioned"] = rec["company_mentioned"] or co
                if row["angle"] not in rec["angles"]:
                    rec["angles"].append(row["angle"])
        # classify + coverage
        for u, rec in seen.items():
            types = []
            for st, pat in SOURCE_TYPES.items():
                if st == "company_site":
                    if p["domain"] in u:
                        types.append(st)
                    continue
                if pat and pat.search(u):
                    types.append(st)
            rec["source_types"] = types or ["other_web"]
            # a source "yields" only if it names the person
            if rec["named"]:
                for t in types:
                    coverage[t] = coverage.get(t, 0) + 1
            if MEDIA_PAT.search(u):
                rec["is_media"] = True
        strong = [r for r in seen.values() if r["named"] and r["company_mentioned"]]
        named_only = [r for r in seen.values() if r["named"] and not r["company_mentioned"]]
        media = [r for r in seen.values() if r.get("is_media") and (r["named"] or r["company_mentioned"])]
        for m in media:
            m["walled"] = bool(WALLED_PAT.search(m["url"]))
        out[key] = {
            "person": p["name"], "company": p["company"],
            "unique_urls": len(seen),
            "strong_hits": sorted(strong, key=lambda r: -len(r["angles"]))[:40],
            "named_only_hits": sorted(named_only, key=lambda r: -len(r["angles"]))[:20],
            "coverage": {k: v for k, v in coverage.items() if v},
            "coverage_zero": [k for k, v in coverage.items() if not v],
        }
        media_index[key] = sorted(media, key=lambda r: (not r["named"], r["url"]))
    json.dump(out, open(os.path.join(HERE, "sweep_triage.json"), "w"), indent=2)
    json.dump(media_index, open(os.path.join(HERE, "media_candidates_triaged.json"), "w"), indent=2)
    print(f"{'person':<20} {'urls':>5} {'strong':>7} {'named':>6} {'media':>6}  coverage_types")
    for p in PEOPLE:
        k = p["key"]
        o = out[k]
        print(f"{k:<20} {o['unique_urls']:>5} {len(o['strong_hits']):>7} "
              f"{len(o['named_only_hits']):>6} {len(media_index[k]):>6}  "
              f"{','.join(sorted(o['coverage']))}")


if __name__ == "__main__":
    main()
