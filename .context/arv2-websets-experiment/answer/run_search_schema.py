"""Same 72 questions as run_answer.py, but through POST /search with systemPrompt + outputSchema.

type=auto, 6 results, full text (3000 chars) so the quote guard can run, no date bounds (so the
retrieval difference against Answer is Exa's own choice, not ours). A second mode, --bounded,
adds startPublishedDate = 24 months ago on the stage gate only.
"""
from __future__ import annotations
import json, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent))
from exa_common import ledger_append, request, save_raw  # noqa: E402
import run_answer as A  # noqa: E402

BOUNDED = "--bounded" in sys.argv

def ask(company: str, url: str, gate: str) -> dict:
    spec = A.GATES[gate]
    query = (f"Company: {company} (website {url}).\nTest to verify: {spec['rule']}.\nHow it is tested: {spec['test']}\n"
             "Decide pass, fail or unclear for THIS company today, citing the freshest relevant source.")
    body = {"query": query, "type": "auto", "numResults": 6, "contents": {"text": {"maxCharacters": 3000}},
            "systemPrompt": A.SYSTEM_PROMPT, "outputSchema": A.OUTPUT_SCHEMA}
    if BOUNDED and gate == "stage":
        body["startPublishedDate"] = "2024-09-10T00:00:00.000Z"
    started = time.monotonic()
    status, out = request("POST", "https://api.exa.ai/search", body, timeout=180)
    elapsed = round(time.monotonic() - started, 1)
    slug = "".join(ch if ch.isalnum() else "_" for ch in company)[:30]
    tag = "searchB" if BOUNDED else "search"
    out["_request"] = body
    save_raw(f"{tag}_{slug}_{gate}", out)
    cost = float(((out.get("costDollars") or {}).get("total")) or 0)
    ledger_append({"arm": "S2", "provider": "exa_search_schema", "bounded": BOUNDED, "label": f"{slug}:{gate}", "http": status, "cost_usd": cost, "elapsed_s": elapsed})
    raw_out = out.get("output")
    content = raw_out.get("content") if isinstance(raw_out, dict) else raw_out
    if isinstance(content, str):
        try: content = json.loads(content)
        except Exception: content = None
    answer = content if isinstance(content, dict) else {"verdict": "unclear", "reasoning": f"no structured output (http {status}): {str(raw_out)[:100]}", "evidence_quote": "", "evidence_url": "", "evidence_date": ""}
    answer["_cost_usd"] = cost; answer["_elapsed_s"] = elapsed
    answer["_results"] = [(r.get("publishedDate") or "")[:10] + " " + (r.get("url") or "") for r in out.get("results") or []][:6]
    return answer

if __name__ == "__main__":
    companies = json.loads((HERE / "companies.json").read_text())
    results = {}; total = 0.0
    for c in companies:
        results[c["name"]] = {}
        for gate in A.GATES:
            a = ask(c["name"], c["url"], gate); results[c["name"]][gate] = a; total += a["_cost_usd"]
            print(f"{c['name']:22} {gate:9} {str(a.get('verdict')):7} ${a['_cost_usd']:.4f} {a['_elapsed_s']:5.1f}s | {str(a.get('reasoning',''))[:100]}", flush=True)
    (HERE / ("search_schema_bounded.json" if BOUNDED else "search_schema.json")).write_text(json.dumps(results, indent=2))
    print(f"TOTAL ${total:.3f}")
