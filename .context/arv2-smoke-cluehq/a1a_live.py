"""A1a — live HTTP fetch of cluehq.ai (browser UA), discover subpages, fetch them. Timed."""

import json
import re
import time

import clue_lib as L

t_phase = time.time()
ROOT = "https://www.cluehq.ai"

pages = {}
r = L.live_fetch(ROOT, label="root")
pages[ROOT] = r

# discover internal links from the root HTML
links = set()
if r["status"] == 200:
    for m in re.finditer(r'href=["\']([^"\']+)["\']', r["text"]):
        h = m.group(1)
        if h.startswith("/") and not h.startswith("//"):
            links.add(ROOT + h.split("#")[0].rstrip("/"))
        elif h.startswith(ROOT):
            links.add(h.split("#")[0].rstrip("/"))
links.discard(ROOT)
links.discard("")
links = sorted(links)
print("discovered internal links:", links, flush=True)

# fetch up to 6 subpages
for u in links[:6]:
    slug = re.sub(r"[^a-z0-9]+", "_", u.replace(ROOT, "").lower()).strip("_") or "root2"
    pages[u] = L.live_fetch(u, label=slug)
    time.sleep(0.3)

summary = {
    "root": ROOT,
    "discovered_links": links,
    "fetched": {
        u: {
            "http": p["status"],
            "elapsed_s": p["elapsed_s"],
            "bytes": len(p["text"]),
            "server": (p["headers"] or {}).get("Server") or (p["headers"] or {}).get("server"),
            "content_type": (p["headers"] or {}).get("Content-Type")
            or (p["headers"] or {}).get("content-type"),
            "first_400": p["text"][:400],
        }
        for u, p in pages.items()
    },
}
json.dump(summary, open("a1a_live_summary.json", "w"), indent=2)
el = time.time() - t_phase
L.timing_record("A1a_live_http_fetch", el, f"{len(pages)} pages via urllib+browser UA")
print(f"A1a done in {el:.1f}s; spend so far ${L.total_spend()}")
