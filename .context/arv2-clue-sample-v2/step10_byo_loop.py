"""Step 10 — measure the BUILD-YOUR-OWN alternative to an Exa deep call.

The step-3 call (deep-reasoning, no outputSchema) returned NO synthesis but DID return its 23-page
research corpus (124,620 chars of primary sources). That corpus is exactly what a self-built loop
would assemble from `search` + `contents`. So: feed it to the cheap model with the SAME 12-section
charter the Exa deep call used, and compare report against report, dollar against dollar.

Retrieval half is priced from this run's observed Exa unit costs:
  neural search  $0.007 flat (10 results, text included)
  contents       $0.001 / page   (measured: 6 pages = $0.006)
"""

import json

from clue_lib import openrouter, save_raw, total_spend

deep = json.load(open("raw/account_deep_lassie.json"))
pages = deep["results"]
SYS_CHARTER = deep["_request"]["systemPrompt"]

corpus_parts, total_chars = [], 0
for p in pages:
    text = p.get("text") or ""
    total_chars += len(text)
    corpus_parts.append(f"===== SOURCE: {p.get('url')}\nTITLE: {p.get('title')}\n{text}")
corpus = "\n\n".join(corpus_parts)

print(f"corpus: {len(pages)} pages, {total_chars} chars")

USER = (
    "Below is the complete research corpus retrieved for this account. Write the dossier described "
    "in your instructions using ONLY these sources. Every fact needs a verbatim quote copied from "
    "the corpus and the SOURCE url it came from. Write NOT FOUND rather than guessing.\n\n" + corpus
)

MODEL = "openai/gpt-5-mini"
resp = openrouter(
    MODEL,
    [{"role": "system", "content": SYS_CHARTER}, {"role": "user", "content": USER}],
    label="byo_synthesis_gpt5mini_minimal",
    timeout=900,
    reasoning={"effort": "minimal"},
)

report = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
open("account_report_byo.md", "w").write(report)
usage = resp.get("usage") or {}
cost = usage.get("cost") or (usage.get("cost_details") or {}).get("upstream_inference_cost") or 0

SEARCH_UNIT, CONTENTS_UNIT = 0.007, 0.001
retrieval_est = SEARCH_UNIT * 2 + CONTENTS_UNIT * len(pages)  # 2 planned queries + 23 pages
result = {
    "pages": len(pages),
    "corpus_chars": total_chars,
    "synthesis_model": MODEL + "@minimal",
    "synthesis_cost_usd": round(float(cost), 5),
    "synthesis_elapsed_s": resp.get("_elapsed_s"),
    "synthesis_usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")},
    "retrieval_cost_est_usd": round(retrieval_est, 5),
    "byo_total_est_usd": round(float(cost) + retrieval_est, 5),
    "exa_deep_reasoning_actual_usd": 0.021,
    "report_chars": len(report),
    "exa_report_chars": len(open("account_report.md").read()),
}
save_raw("byo_loop_measurement", result)
print(json.dumps(result, indent=2))
print("total spend $", total_spend())
print("\n---- first 1200 chars of the BYO report ----\n", report[:1200])
