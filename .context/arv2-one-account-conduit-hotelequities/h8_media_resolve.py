"""H8 — resolve the media layer to PLAYABLE sources (audio preferred over video).

Proven on the Zafran run: a YouTube URL is billed as VIDEO (~91 tokens/sec); an MP3 is billed as
AUDIO (~25 tokens/sec) — roughly 3.6x cheaper for the same minutes. So: find the MP3 enclosure
first (episode page -> audio src, or the show RSS), and fall back to YouTube only if no audio
exists.

Targets, in priority order: Ben Rafter (CEO, executive sponsor, "a technology entrepreneur" — the
most important voice in this account), then Al Smith (COO), then the champion/evaluator.
"""
import json
import re
import sys
import time

sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

EPISODE_PAGES = [
    ("rafter_ai_payoff", "Ben Rafter",
     "https://podcast.hospitalitydaily.com/ben-rafter-ai-hotel-performance/"),
    ("rafter_tech_ceo", "Ben Rafter", "https://podcast.hospitalitydaily.com/ben-rafter/"),
    ("rafter_ai_labor", "Ben Rafter", "https://podcast.hospitalitydaily.com/ben-rafter-ai-labor/"),
    ("rafter_tech", "Ben Rafter", "https://podcast.hospitalitydaily.com/ben-rafter-tech/"),
    ("rafter_owner_econ", "Ben Rafter",
     "https://podcast.hospitalitydaily.com/ben-rafter-owner-economics/"),
    ("rafter_no_vacancy", "Ben Rafter",
     "https://novacancynews.com/springboards-ben-rafter-on-building-smarter-faster-and-more-human-hotels/"),
    ("rafter_tmg", "Ben Rafter",
     "https://www.travelmediagroup.com/190-tmg-hospitality-trailblazers-ben-rafter/"),
]

AUDIO_RE = re.compile(r'https?://[^\s"\'<>()]+?\.mp3[^\s"\'<>()]*', re.I)
RSS_RE = re.compile(r'https?://[^\s"\'<>()]+?(?:rss|feed)[^\s"\'<>()]*', re.I)
DUR_RE = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})|(\d{1,2}):(\d{2})')
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def secs(h, m, s=None):
    return int(h) * 3600 + int(m) * 60 + int(s or 0)


t_all = time.time()
index = []

print("== A. episode pages -> mp3 enclosure ==")
for slug, person, url in EPISODE_PAGES:
    r = C.live_fetch(url, label=f"h8_page_{slug}", timeout=25, retries=1)
    body = r["text"] if r["status"] == 200 else ""
    mp3s = sorted(set(AUDIO_RE.findall(body)))
    feeds = sorted({f for f in RSS_RE.findall(body) if "rss" in f.lower() or "feed" in f.lower()})
    tm = TITLE_RE.search(body)
    # duration hints
    dur = None
    m = re.search(r'"duration"\s*:\s*"?(\d+)', body) or re.search(r'itunes:duration>(\d+)', body)
    if m:
        try:
            dur = int(m.group(1))
        except Exception:
            dur = None
    row = {"slug": slug, "person": person, "page_url": url, "http": r["status"],
           "page_title": (tm.group(1).strip()[:220] if tm else None),
           "mp3_candidates": mp3s[:6], "feed_candidates": feeds[:6],
           "duration_seconds_hint": dur, "bytes": len(body)}
    index.append(row)
    print(f"   {slug:20s} http={r['status']:3d} mp3={len(mp3s)} feeds={len(feeds)} "
          f"dur={dur} :: {(row['page_title'] or '')[:70]}")
    for u in mp3s[:3]:
        print(f"        mp3: {u[:150]}")

print("\n== B. Hospitality Daily show RSS (all Rafter episodes + exact durations) ==")
rss_tries = ["https://feeds.transistor.fm/hospitality-daily",
             "https://podcast.hospitalitydaily.com/rss",
             "https://feeds.buzzsprout.com/hospitality-daily.rss"]
rss_hit = None
for u in rss_tries:
    r = C.live_fetch(u, label="h8_rss_" + u.split("/")[-1][:20], accept="application/rss+xml",
                     timeout=25, retries=1)
    if r["status"] == 200 and "<item" in r["text"]:
        rss_hit = {"url": u, "text": r["text"]}
        print(f"   RSS OK {u} bytes={len(r['text'])}")
        break
    print(f"   rss try {u} -> http={r['status']}")

rafter_eps = []
if rss_hit:
    items = re.findall(r"<item>(.*?)</item>", rss_hit["text"], re.S)
    print(f"   items={len(items)}")
    for it in items:
        tt = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        title = (tt.group(1) if tt else "").strip()
        if "rafter" not in title.lower():
            continue
        enc = re.search(r'<enclosure[^>]*url="([^"]+)"', it)
        ln = re.search(r'length="(\d+)"', it)
        du = re.search(r"<itunes:duration>(.*?)</itunes:duration>", it)
        pb = re.search(r"<pubDate>(.*?)</pubDate>", it)
        lk = re.search(r"<link>(.*?)</link>", it)
        d = (du.group(1).strip() if du else "")
        dsec = None
        if d.isdigit():
            dsec = int(d)
        elif ":" in d:
            p = [int(x) for x in d.split(":")]
            dsec = secs(*p) if len(p) == 3 else p[0] * 60 + p[1]
        rafter_eps.append({"title": title, "mp3": enc.group(1) if enc else None,
                           "bytes": int(ln.group(1)) if ln else None,
                           "itunes_duration": d, "duration_seconds": dsec,
                           "pubDate": pb.group(1).strip() if pb else None,
                           "link": lk.group(1).strip() if lk else None})
    print(f"   Rafter episodes in feed: {len(rafter_eps)}")
    for e in rafter_eps:
        print(f"      - {e['pubDate'][:16] if e['pubDate'] else '?':16s} {e['itunes_duration']:>8s} "
              f"{e['title'][:80]}")

out = {"episode_pages": index, "show_rss": (rss_hit or {}).get("url"),
       "rafter_episodes_from_rss": rafter_eps}
json.dump(out, open("h8_media_resolve.json", "w"), indent=2)
C.timing_record("H8_media_resolve", time.time() - t_all,
                f"{len(EPISODE_PAGES)} pages + rss")
print(f"\nH8 {round(time.time()-t_all,1)}s spend={C.total_spend()}")
