"""Step 11 — pricing the recommendation: can a $0.007 search settle the hard disqualifier BEFORE
any deep spend?

The picked account was disqualified by a $0.007 gap-fill search AFTER a $0.029 deep call had
already run and reported the qualifier as NOT FOUND. If the cheap search alone can settle the
qualifier, the correct production order is qualifier-probe -> tier gate -> deep call, and every
disqualified account costs ~$0.01 instead of ~$0.12. This step tests that on three untouched
candidates from the same discovery pass.
"""

import json
import re

from clue_lib import exa

CANDIDATES = [
    ("asheville", "Asheville Gastroenterology Associates", "ashevillegastro.com"),
    ("athens", "Athens Gastroenterology Center", "athensgicenter.com"),
    ("gainesville", "Gastroenterology Associates of Gainesville", "gastrogainesville.com"),
]

PAT = re.compile(
    r"(gGastro|gMed|Modernizing Medicine|ModMed|Epic|eClinicalWorks|eCW|athenahealth|NextGen|"
    r"Allscripts|Greenway|Cerner|Meditech|Practice Fusion|AdvancedMD|Provation|Klara)",
    re.I,
)

summary = {}
for key, name, domain in CANDIDATES:
    r = exa(
        {
            "query": (
                f"{name} {domain} electronic health record EHR practice management system "
                f"gGastro Modernizing Medicine ModMed Epic eClinicalWorks patient portal vendor "
                f"case study press release job posting"
            ),
            "type": "auto",
            "numResults": 10,
            "contents": {"text": {"maxCharacters": 3000}},
            "stream": False,
        },
        label=f"step11_qualify_{key}",
        timeout=180,
    )
    hits = {}
    for item in r.get("results") or []:
        text = (item.get("title") or "") + " " + (item.get("text") or "")
        for m in PAT.finditer(text):
            token = m.group(1)
            hits.setdefault(token, [])
            if len(hits[token]) < 2:
                start = max(0, m.start() - 140)
                hits[token].append(
                    {
                        "url": item.get("url"),
                        "snippet": text[start : m.start() + 200].replace("\n", " "),
                    }
                )
    summary[key] = {"name": name, "domain": domain, "vendor_mentions": hits}
    print(f"\n== {name} ({domain})")
    for token, ev in hits.items():
        print(f"   {token}: {len(ev)} hit(s)")
        for e in ev[:1]:
            print(f"      {e['url']}")
            print(f"      ...{e['snippet'][:260]}")

json.dump(summary, open("qualifier_probe.json", "w"), indent=2)
