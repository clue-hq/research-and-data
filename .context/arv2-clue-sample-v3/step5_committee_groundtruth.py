"""Step 5 — committee ground truth from the OPEN WEB (protocol item 1), before Apollo touches it.

The founders are already confirmed by the company's own /company page + a16z + Sequoia + the wire
release. What is missing is the GTM leadership the job reqs prove exists ("You report to the
Director of Growth"). LinkedIn via Exa, forced to mention Probook.
"""

import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

SEARCHES = [
    (
        "ct1_linkedin_gtm_leaders",
        {
            "query": "Director of Growth / go-to-market and sales leadership at Probook, the AI "
            "operating system for home services in New York",
            "type": "auto",
            "numResults": 15,
            "includeDomains": ["linkedin.com"],
            "includeText": ["Probook"],
            "contents": {"text": {"maxCharacters": 2000}},
        },
    ),
    (
        "ct2_linkedin_team_any",
        {
            "query": "person who works at Probook (probook.ai) New York — AI dispatch for "
            "plumbing HVAC electrical contractors — LinkedIn profile",
            "type": "auto",
            "numResults": 15,
            "includeDomains": ["linkedin.com"],
            "includeText": ["Probook"],
            "contents": {"text": {"maxCharacters": 2000}},
        },
    ),
]

for label, payload in SEARCHES:
    r = C.exa(payload, label=label)
    for res in r.get("results") or []:
        txt = (res.get("text") or "").replace("\n", " ")[:260]
        print(f"  - {res.get('title')} | {res.get('url')}\n      {txt}", flush=True)
    print()

print("TOTAL:", C.total_spend())
