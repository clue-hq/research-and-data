"""Z3 — resolve the two media items for the Gemini layer, and bind the Nick Fisher identity."""
import json, re, sys, time, urllib.parse
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

t0 = time.time(); res = {}

# ---- A. Sanaz podcast: RSS -> enclosure + itunes:duration (FREE) ----------
print("== A. Boardroom Club RSS ==")
rss = C.live_fetch("https://anchor.fm/s/f695d6d8/podcast/rss", label="boardroom_rss",
                   accept="application/rss+xml")
items = re.findall(r"<item>(.*?)</item>", rss["text"], re.S)
print(f"   rss http={rss['status']} items={len(items)}")
hit = None
for it in items:
    title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
    t = (title.group(1) if title else "").strip()
    if "sanaz" in t.lower():
        enc = re.search(r'<enclosure[^>]*url="([^"]+)"[^>]*', it)
        dur = re.search(r"<itunes:duration>(.*?)</itunes:duration>", it)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", it)
        link = re.search(r"<link>(.*?)</link>", it)
        length = re.search(r'length="(\d+)"', it)
        hit = {"title": t, "enclosure": enc.group(1) if enc else None,
               "itunes_duration": dur.group(1) if dur else None,
               "pubDate": pub.group(1) if pub else None,
               "link": link.group(1) if link else None,
               "enclosure_bytes": int(length.group(1)) if length else None}
        break
res["sanaz_podcast"] = hit
print("   ", json.dumps(hit, indent=1)[:900])

# ---- B. Nick Fisher <-> Cocktail Chemistry identity binding ---------------
print("\n== B. identity binding + youtube video pick ==")
bind = C.exa_contents(["https://www.cocktailchemistrylab.com/about",
                       "https://www.simonandschuster.com/authors/Nick-Fisher/177280135",
                       "https://www.linkedin.com/pulse/why-i-joined-zafran-security-nick-fisher-jqinf"],
                      label="z3_identity_bind", text_chars=6000)
res["identity_binding"] = [{"url": x.get("url"), "title": x.get("title"),
                            "text": (x.get("text") or "")[:3000]}
                           for x in (bind.get("results") or [])]
for x in res["identity_binding"]:
    print(f"   {x['url']}  ({len(x['text'])} chars)")

vids = C.exa({"query": "Cocktail Chemistry youtube video how to make cocktail from movie",
              "type": "auto", "numResults": 10,
              "includeDomains": ["youtube.com", "www.youtube.com"],
              "contents": {"text": {"maxCharacters": 1200}}}, label="z3_cc_videos")
res["cc_videos"] = [{"url": x.get("url"), "title": x.get("title"),
                     "published": x.get("publishedDate"),
                     "author": x.get("author"),
                     "text_head": (x.get("text") or "")[:400]}
                    for x in (vids.get("results") or [])]
for v in res["cc_videos"]:
    print(f"   - {v['title']} | {v['author']} | {v['url']}")

json.dump(res, open("z3_media_resolve.json", "w"), indent=2)
C.timing_record("Z3_media_resolve", time.time() - t0, "rss + identity + video list")
print(f"\nZ3 {round(time.time()-t0,1)}s spend={C.total_spend()}")
