"""A1c — the Exa side of the comparison: is cluehq.ai in Exa's index, and is the copy current?

Four probes, each timed + costed:
  1. /contents on the live URL, cached (whatever the index holds)
  2. /contents on the same URL with livecrawl="always" (force a fresh crawl)
  3. /search type=auto, natural-language query naming the company
  4. /search restricted to includeDomains=["cluehq.ai"] (what pages does Exa hold for the domain?)
"""

import json
import time

import clue_lib as L

t0 = time.time()
ROOT = "https://www.cluehq.ai"
res = {}

res["contents_cached"] = L.exa_contents([ROOT], label="a1_contents_cached", text_chars=10000)
time.sleep(1)
res["contents_livecrawl"] = L.exa_contents(
    [ROOT], label="a1_contents_livecrawl", text_chars=10000, livecrawl="always"
)
time.sleep(1)
res["search_nl"] = L.exa(
    {
        "query": "Clue cluehq.ai agentic ABM platform AI agents for account-based marketing",
        "type": "auto",
        "numResults": 10,
    },
    label="a1_search_nl",
)
time.sleep(1)
res["search_domain"] = L.exa(
    {
        "query": "Clue agentic ABM platform",
        "type": "auto",
        "numResults": 10,
        "includeDomains": ["cluehq.ai"],
    },
    label="a1_search_domain",
)

digest = {}
for k, v in res.items():
    rs = v.get("results") or []
    digest[k] = {
        "http": v.get("_http_status"),
        "elapsed_s": v.get("_elapsed_s"),
        "cost_usd": (v.get("costDollars") or {}).get("total"),
        "n_results": len(rs),
        "results": [
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "publishedDate": r.get("publishedDate"),
                "author": r.get("author"),
                "text_chars": len(r.get("text") or ""),
                "text_head": (r.get("text") or "")[:600],
            }
            for r in rs
        ],
        "statuses": v.get("statuses"),
    }
json.dump(digest, open("a1c_exa_digest.json", "w"), indent=2)

el = time.time() - t0
L.timing_record("A1c_exa_probes", el, "2 contents (cached+livecrawl) + 2 searches")
print(f"A1c done in {el:.1f}s; total spend ${L.total_spend()}")
