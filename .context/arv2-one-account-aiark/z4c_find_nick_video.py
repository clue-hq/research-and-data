"""Z4c — find a Cocktail Chemistry video where Nick Fisher talks about himself / the channel."""
import json, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402
t0=time.time()
out = C.exa({"query": "Cocktail Chemistry channel announcement book Nick Fisher behind the scenes "
                      "why I started thank you subscribers",
             "type": "auto", "numResults": 10,
             "includeDomains": ["youtube.com", "www.youtube.com"],
             "contents": {"text": {"maxCharacters": 1500}}}, label="z4c_nick_video_hunt")
rows=[{"url": x.get("url"), "title": x.get("title"), "author": x.get("author"),
       "published": x.get("publishedDate"), "head": (x.get("text") or "")[:500]}
      for x in (out.get("results") or [])]
for r in rows: print(f"- {r['title']} | {r['author']} | {r['published']} | {r['url']}")
json.dump(rows, open("z4c_nick_video_candidates.json","w"), indent=2)
C.timing_record("Z4c_nick_video_hunt", time.time()-t0, "exa search")
