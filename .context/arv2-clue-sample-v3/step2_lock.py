"""Step 2 — domain lock + qualifier probe for the chosen candidate (Probook).

One Exa search: locks the official domain, and surfaces careers/team pages in the same $0.007.
"""

import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

r = C.exa(
    {
        "query": "Probook AI operating system for home services plumbing HVAC electrical "
        "contractors — official company website, about, team and open roles",
        "type": "auto",
        "numResults": 10,
        "contents": {"text": {"maxCharacters": 2500}},
    },
    label="q1_probook_domain_lock",
)
for res in r.get("results") or []:
    print(f"  - {res.get('title')} | {res.get('url')}", flush=True)

print("\nTOTAL:", C.total_spend())
