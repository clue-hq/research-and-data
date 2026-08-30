"""Step 4 — cheap gap-fills (<=4 calls) for the criticals the deep report marked NOT FOUND.

Gaps the deep report left, and their disposition:
  headcount / dept split ......... CLOSED by Apollo org enrich (tier-1 api) - no call spent
  outbound + CRM tooling ......... CLOSED by Apollo technographics - no call spent
  pre-Series-A round ............. G1 (cheap search)  <- funding is a named critical
  GTM posting locations/bands/dates G2 (cheap /contents on the Ashby postings)
  named customers / team page .... G3 (cheap search)
"""

import json
import time

from clue_lib import EXA_KEY, ledger_append, save_raw, total_spend, _request


def exa_contents(urls, label, text_chars=6000):
    status, hdrs, text, elapsed = _request(
        "https://api.exa.ai/contents",
        method="POST",
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
        body={"urls": urls, "text": {"maxCharacters": text_chars}},
        timeout=180,
    )
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    save_raw(label, out)
    cost = (out.get("costDollars") or {}).get("total")
    ledger_append(
        {
            "provider": "exa",
            "label": label,
            "op": "contents",
            "http": status,
            "elapsed_s": elapsed,
            "cost_usd": cost,
            "cost_breakdown": out.get("costDollars"),
        }
    )
    print(f"  exa[{label}] http={status} {elapsed}s cost={cost}", flush=True)
    return out


def exa_search(payload, label):
    from clue_lib import exa

    return exa(payload, label=label, timeout=180)


# --- G1: the pre-Series-A round (total raised $47M - $35M Series A = $12M unexplained) ---
g1 = exa_search(
    {
        "query": (
            "Lassie lassie.ai dental AI startup seed round funding before Series A, Steijn Pelle "
            "Frederic Renken raised seed, total capital raised $47 million"
        ),
        "type": "auto",
        "numResults": 8,
        "systemPrompt": (
            "Only the San Francisco AI company Lassie (lassie.ai) that automates dental/medical "
            "practice administration. NEVER the Swedish pet-insurance company lassie.co, never "
            "the TV collie. Report the seed/pre-seed round: amount, date, lead investor, "
            "participants, with a verbatim quote and URL, or say not found."
        ),
        "contents": {"text": {"maxCharacters": 3000}},
        "stream": False,
    },
    "g1_seed_round",
)
time.sleep(1.0)

# --- G2: the Ashby postings themselves (location, comp band, posted date, full GTM language) ---
ASHBY = [
    "https://jobs.ashbyhq.com/lassie/d7f41c77-908c-4206-852b-a99a17f9a867",  # GTM Associate
    "https://jobs.ashbyhq.com/lassie/297fd72f-fe6d-40f1-8931-89085e66fa2f",  # Head of Marketing
    "https://jobs.ashbyhq.com/lassie/19493179-d4ea-476e-af9f-218684228879",  # CSM
    "https://jobs.ashbyhq.com/lassie/b5013359-447e-445d-b3af-bc304e89a654",  # Business Operations
    "https://jobs.ashbyhq.com/lassie/3b76ef54-2d0f-4c64-a16a-4d76c3899afd",  # Head of Finance
    "https://jobs.ashbyhq.com/lassie",  # the index: the full open-role list
]
g2 = exa_contents(ASHBY, "g2_ashby_postings")
time.sleep(1.0)

# --- G3: named customers / case studies / the team page ---
g3 = exa_search(
    {
        "query": (
            "Lassie lassie.ai dental practice AI customer case study testimonial named practice, "
            "Lassie team page employees leadership, Lassie pricing"
        ),
        "type": "auto",
        "numResults": 10,
        "systemPrompt": (
            "Only the San Francisco AI company Lassie (lassie.ai) automating dental/medical "
            "practice administration - never the pet-insurance Lassie, never the TV collie. Find "
            "named customer practices, testimonials, published pricing, and any team/about page "
            "listing employees. Quote verbatim with URLs; say not found rather than guessing."
        ),
        "contents": {"text": {"maxCharacters": 4000}},
        "stream": False,
    },
    "g3_customers_team",
)

print("\n=== G1 seed round ===")
for it in g1.get("results") or []:
    print("-", it.get("url"), "|", (it.get("title") or "")[:80])
print("\n=== G2 postings ===")
for it in g2.get("results") or []:
    print("-", it.get("url"), "chars", len(it.get("text") or ""))
print("\n=== G3 customers/team ===")
for it in g3.get("results") or []:
    print("-", it.get("url"), "|", (it.get("title") or "")[:80])
print("\ntotal spend $", total_spend())
