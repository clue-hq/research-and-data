"""Step 4 — ≤4 cheap gap-fill calls for the named criticals the one deep call left open.

Open after step 3b: (1) EHR / portal vendor + the gGastro verdict — the #1 qualifier, still
NOT FOUND; (2) the full physician roster + provider count; (3) prior-auth evidence; (4) the
administrative/leadership roster. Cheap `/contents` (page fetch) and `/search` only — no deep call.
"""

import json

from clue_lib import RAW, _request, EXA_KEY, ledger_append, save_raw, exa
import os


def exa_contents(urls, label, *, max_chars=6000):
    body = {
        "urls": urls,
        "text": {"maxCharacters": max_chars},
        "livecrawl": "preferred",
    }
    status, hdrs, text, elapsed = _request(
        "https://api.exa.ai/contents",
        method="POST",
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
        body=body,
        timeout=240,
    )
    try:
        out = json.loads(text)
    except Exception:
        out = {"_unparsed": text[:4000]}
    out["_http_status"] = status
    out["_elapsed_s"] = elapsed
    out["_request"] = body
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
    print(f"  exa[{label}] contents http={status} {elapsed}s cost={cost}", flush=True)
    return out


# --- G1: fetch the practice's own key pages (roster, referring physicians, forms, contact) ---
g1 = exa_contents(
    [
        "https://charlestongi.com/doctors-and-staff/",
        "https://charlestongi.com/referring-physicians/",
        "https://charlestongi.com/for-patients/patient-forms/",
        "https://charlestongi.com/contact-us/",
    ],
    "step4_g1_own_pages",
    max_chars=9000,
)
for res in (g1.get("results") or []):
    print("   *", res.get("url"), len(res.get("text") or ""))

# --- G2: the EHR / portal vendor (the #1 qualifier) ---
g2 = exa(
    {
        "query": (
            "Charleston GI Specialists charlestongi.com \"My GI Patient Portal\" patient portal "
            "login electronic health record EHR practice management system vendor"
        ),
        "type": "auto",
        "numResults": 10,
        "contents": {"text": {"maxCharacters": 3000}},
        "stream": False,
    },
    label="step4_g2_ehr_portal",
    timeout=180,
)

# --- G3: job postings => prior-auth / referral-coordinator workload + named EHR ---
g3 = exa(
    {
        "query": (
            "Charleston Gastroenterology Specialists Charleston GI jobs hiring "
            "\"prior authorization\" OR \"referral coordinator\" OR \"insurance verification\" "
            "OR \"medical records\" Charleston SC gastroenterology practice careers"
        ),
        "type": "auto",
        "numResults": 10,
        "contents": {"text": {"maxCharacters": 3000}},
        "stream": False,
    },
    label="step4_g3_priorauth_jobs",
    timeout=180,
)

# --- G4: administrative / leadership roster ---
g4 = exa(
    {
        "query": (
            "Wanda Punteney Charleston Gastroenterology Specialists Chief Executive Officer "
            "practice administrator billing manager revenue cycle privacy officer leadership team "
            "Charleston GI LinkedIn"
        ),
        "type": "auto",
        "numResults": 10,
        "contents": {"text": {"maxCharacters": 3000}},
        "stream": False,
    },
    label="step4_g4_leadership",
    timeout=180,
)

for name, r in (("g2", g2), ("g3", g3), ("g4", g4)):
    print(f"  -- {name} results:")
    for item in (r.get("results") or [])[:10]:
        print("   *", (item.get("title") or "")[:80], "|", item.get("url"))
