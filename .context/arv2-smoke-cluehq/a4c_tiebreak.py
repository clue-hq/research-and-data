"""A4c — tie-break round.

(1) Resolve one H2 gate ambiguity: Oscilar is founder-self-funded ($20M, TechCrunch 2023) yet
    CB Insights labels it "Series A". Did an external priced round land since?
(2) The three clear leaders all carry a Tier-1 Q1 (a GTM job req). The 4th/5th contenders
    (Arintra, Uptiq, Vendelux, Translucent) cleared only Q4. Look for their Q1 on the job boards
    before deciding — the rubric's heaviest criterion should not be decided by a coin flip.
"""

import json
import time

import clue_lib as L

t_phase = time.time()
BOARDS = [
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "ashbyhq.com",
    "careers.smartrecruiters.com",
    "wellfound.com",
]

PROBES = [
    (
        "t_oscilar_round",
        {
            "query": "Oscilar raises funding round Series A Series B 2026 investors Neha Narkhede",
            "type": "auto",
            "numResults": 5,
            "startPublishedDate": "2024-01-01T00:00:00.000Z",
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "t_jobs_arintra",
        {
            "query": "Arintra marketing demand generation growth job opening",
            "type": "auto",
            "numResults": 5,
            "includeDomains": BOARDS,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "t_jobs_uptiq",
        {
            "query": "Uptiq marketing demand generation growth job opening banks credit unions",
            "type": "auto",
            "numResults": 5,
            "includeDomains": BOARDS,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "t_jobs_vendelux",
        {
            "query": "Vendelux marketing demand generation growth job opening events intelligence",
            "type": "auto",
            "numResults": 5,
            "includeDomains": BOARDS,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
    (
        "t_jobs_translucent",
        {
            "query": "Translucent AI healthcare finance marketing growth job opening New York",
            "type": "auto",
            "numResults": 5,
            "includeDomains": BOARDS,
            "contents": {"text": {"maxCharacters": 1200}},
        },
    ),
]

out = {}
for label, payload in PROBES:
    t0 = time.time()
    resp = L.exa(payload, label=label)
    out[label] = {
        "query_verbatim": payload["query"],
        "payload": payload,
        "http": resp.get("_http_status"),
        "elapsed_s": resp.get("_elapsed_s"),
        "cost_usd": (resp.get("costDollars") or {}).get("total"),
        "results": [
            {
                "url": r.get("url"),
                "title": r.get("title"),
                "publishedDate": r.get("publishedDate"),
                "text": r.get("text") or "",
            }
            for r in (resp.get("results") or [])
        ],
    }
    L.timing_record(f"A4c_{label}", time.time() - t0, "tie-break")
    time.sleep(1.1)

json.dump(out, open("tiebreak_raw.json", "w"), indent=2)
el = time.time() - t_phase
L.timing_record("A4c_tiebreak", el, f"{len(PROBES)} probes")
print(f"A4c done in {el:.1f}s; total spend ${L.total_spend()}")
