"""A1b — live fetch of the real content subpages (assets excluded) + probe common routes."""

import json
import time

import clue_lib as L

t0 = time.time()
ROOT = "https://www.cluehq.ai"
targets = [
    (ROOT + "/privacy", "privacy"),
    (ROOT + "/terms", "terms"),
    # probe routes the brief names, to see whether they exist at all
    (ROOT + "/product", "probe_product"),
    (ROOT + "/how-it-works", "probe_how_it_works"),
    (ROOT + "/pricing", "probe_pricing"),
    (ROOT + "/about", "probe_about"),
]
out = {}
for url, label in targets:
    r = L.live_fetch(url, label=label)
    out[url] = {
        "http": r["status"],
        "elapsed_s": r["elapsed_s"],
        "bytes": len(r["text"]),
        "server": (r["headers"] or {}).get("Server") or (r["headers"] or {}).get("server"),
        "cf_ray": (r["headers"] or {}).get("Cf-Ray") or (r["headers"] or {}).get("cf-ray"),
        "title_snippet": r["text"][:200],
    }
    time.sleep(0.2)

json.dump(out, open("a1b_live_sub.json", "w"), indent=2)
el = time.time() - t0
L.timing_record("A1b_live_subpages", el, f"{len(targets)} urls (2 real + 4 route probes)")
print(f"A1b done in {el:.1f}s")
