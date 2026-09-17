"""Step 11 — the `deep` (non-reasoning) vs `deep-reasoning` datapoint.

Same charter, same query, same single-string outputSchema as the account call; only `type` changes.
List price is deep $12/1k vs deep-reasoning $15/1k, but the observed totals include retrieval, so
measure rather than assume.
"""

import json

from clue_lib import exa, save_raw, total_spend

prev = json.load(open("raw/account_deep_lassie_retry.json"))["_request"]
payload = dict(prev)
payload["type"] = "deep"

resp = exa(payload, label="account_deep_lite_lassie", timeout=900)

raw_out = resp.get("output")
report = ""
if isinstance(raw_out, dict):
    content = raw_out.get("content")
    if isinstance(content, dict):
        report = content.get("report") or json.dumps(content, indent=2)
    elif isinstance(content, str):
        try:
            report = json.loads(content).get("report") or content
        except Exception:
            report = content

open("account_report_deeplite.md", "w").write(report)
notfound = report.count("NOT FOUND")
result = {
    "type": "deep",
    "cost_usd": (resp.get("costDollars") or {}).get("total"),
    "elapsed_s": resp.get("_elapsed_s"),
    "results_returned": len(resp.get("results") or []),
    "report_chars": len(report),
    "not_found_markers": notfound,
    "compare_deep_reasoning": {
        "cost_usd": 0.021,
        "elapsed_s": 43.7,
        "results_returned": 16,
        "report_chars": 19368,
        "not_found_markers": open("account_report.md").read().count("NOT FOUND"),
    },
}
save_raw("deep_vs_deeplite_measurement", result)
print(json.dumps(result, indent=2))
print("total spend $", total_spend())
print("\n---- first 1200 chars ----\n", report[:1200])
