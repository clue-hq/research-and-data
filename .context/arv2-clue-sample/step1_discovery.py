"""Step 1 — Exa discovery over the Insight Health ICP (2 cheap searches, numResults 10).

Excludes the two answer-key domains so the run proves generalization.
"""

import json
import os

from clue_lib import HERE, exa

EXCLUDE = ["digestivehealthcare.net", "eaglemds.com"]

QUERIES = [
    (
        "d1",
        "independent physician-owned gastroenterology practice in the US Southeast "
        "(Georgia, Tennessee, Alabama, South Carolina, North Carolina, Florida) that owns "
        "its own endoscopy center / ambulatory surgery center, 5-50 gastroenterologists",
    ),
    (
        "d2",
        "gastroenterology group practice Southeast US referring physician referral form fax number "
        "prior authorization precertification independent private GI practice endoscopy center",
    ),
]

results = {}
for label, q in QUERIES:
    r = exa(
        {
            "query": q,
            "type": "auto",
            "numResults": 10,
            "excludeDomains": EXCLUDE,
            "contents": {"text": {"maxCharacters": 1200}},
            "stream": False,
        },
        label=f"step1_{label}",
        timeout=180,
    )
    results[label] = r
    for item in r.get("results", []) or []:
        print(
            "   -",
            (item.get("title") or "")[:90],
            "|",
            item.get("url"),
            flush=True,
        )

json.dump(results, open(os.path.join(HERE, "raw", "step1_discovery_all.json"), "w"), indent=2)
