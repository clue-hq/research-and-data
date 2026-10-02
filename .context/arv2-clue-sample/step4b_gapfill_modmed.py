"""Step 4b — the 5th (and last) cheap gap-fill: confirm the hard disqualifier verbatim.

Gap-fill G2 surfaced a ModMed-published customer story titled "Charleston GI Improves Revenue Cycle
with ModMed Suite of Products". ModMed is the vendor of gGastro — the ICP's single hard
disqualifier — so this is the highest-value unresolved fact in the run and worth one more page
fetch. Bundled with three supporting pages so the call stays a single request.
"""

import json

from clue_lib import EXA_KEY, _request, ledger_append, save_raw

URLS = [
    "https://www.modmed.com/resources/gi/charleston-gi-improves-revenue-cycle-with-modmed-suite-of-products",
    "https://charlestongi.com/doctors&staff/wanda-w-punteney/",
    "https://charlestongi.com/careers-portal/",
    "https://easyapply.co/a/e486079d-8a5c-4931-aed6-1ab674610d3e",
]

body = {"urls": URLS, "text": {"maxCharacters": 12000}, "livecrawl": "always"}
status, hdrs, text, elapsed = _request(
    "https://api.exa.ai/contents",
    method="POST",
    headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
    body=body,
    timeout=300,
)
try:
    out = json.loads(text)
except Exception:
    out = {"_unparsed": text[:4000]}
out["_http_status"] = status
out["_elapsed_s"] = elapsed
out["_request"] = body
save_raw("step4b_modmed_confirm", out)
cost = (out.get("costDollars") or {}).get("total")
ledger_append(
    {
        "provider": "exa",
        "label": "step4b_modmed_confirm",
        "op": "contents",
        "http": status,
        "elapsed_s": elapsed,
        "cost_usd": cost,
        "cost_breakdown": out.get("costDollars"),
    }
)
print(f"  exa[step4b] http={status} {elapsed}s cost={cost}")
for res in out.get("results") or []:
    print("=" * 90)
    print(res.get("url"), "|", res.get("title"))
    print((res.get("text") or "")[:5000])
