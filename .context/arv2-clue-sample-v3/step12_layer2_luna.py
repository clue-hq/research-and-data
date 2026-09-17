"""Step 12 — LAYER 2: the display layer, `openai/gpt-5.6-luna` over the Layer-1 payloads.

The split being proved: the backend serves TRUTH (typed claims, provenance, absence-as-an-answer);
a cheap display model turns that truth into human copy. Luna sees ONLY `layer1_payloads.json` — no
research reports, no raw sources — so it cannot introduce a fact the claim store does not hold.
Its measured token usage and cost are the price of the display layer, reported separately.
"""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

MODEL = "openai/gpt-5.6-luna"
payloads = json.load(open("layer1_payloads.json"))

SYSTEM = """You are the DISPLAY layer of an ABM platform. You are given the backend's exact API
payloads for one account and its buying committee, and you turn them into the copy a user reads.

THE ONE HARD RULE: you may not state anything the payload does not contain. No invented numbers,
no invented dates, no inferred employer, no rounded-up metrics, no "likely" or "probably". If a
field is null or an array is empty, that is a real answer — say nothing rather than fill it. Every
quote you show must be copied verbatim from a `quote` / `evidenceSpan` value in the payload.

You are writing for a revenue operator who has 15 seconds. Be concrete and specific. Never use
marketing filler ("innovative", "cutting-edge", "leader in"). Prefer the operator's own words.

Return ONLY this JSON object:

{
  "accountSummary": "<3-5 sentences. What this company is, who it sells to, where it is in its
     lifecycle, and why it is on this list right now. Plain prose, no bullet points.>",
  "whyNow": [            // 3-5 items, the strongest first. Source ONLY from _PROPOSED_SLOTS
                         // ->"account.topSignals[]"->example and the P1-priority neutralFacts.
    {"headline": "<one crisp line, <= 90 chars, states the signal and why it matters>",
     "quote": "<the verbatim quote chip from the payload, trimmed but never reworded>",
     "sourceDomain": "<the sourceDomain from the payload>"}
  ],
  "insightLabels": [     // one per neutralFacts[] entry, in the payload's order
    {"fieldKey": "<the raw fieldKey>",
     "label": "<the humanized rendering of that fieldKey + value, e.g. 'Raised $34M Series A led
        by a16z' — never raw JSON, never the snake_case key>",
     "priority": <the priority from _PROPOSED_SLOTS->"account.neutralFacts[].priority"->example>}
  ],
  "contacts": [          // one per committee member, in the payload's contacts order
    {"contactId": "<the id>",
     "name": "<the name>",
     "roleLabel": "<humanized persona + title, e.g. 'Champion - Director of Growth'>",
     "overview": "<2-4 sentences: what they own, where they came from, and what makes them
        reachable right now. Only from the payload.>",
     "howToOpen": [      // 2-3 lines, each grounded in a specific fact in THIS person's block
       {"line": "<the actual opening line a rep would send or say>",
        "hook": "<the exact fact it uses>",
        "sourceUrl": "<the sourceUrl of that fact from the payload>"}
     ]}
  ]
}"""

USER = (
    "# THE BACKEND PAYLOADS (this is everything you know)\n\n```json\n"
    + json.dumps(payloads, indent=1)
    + "\n```\n\nProduce the display layer now."
)

label = "layer2_luna"
if "--fallback" in sys.argv:
    MODEL = "openai/gpt-5-mini"
    label = "layer2_fallback_gpt5mini"

resp = C.openrouter(
    MODEL,
    [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
    label=label,
    response_format={"type": "json_object"},
    timeout=900,
)
txt = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
if txt.strip().startswith("```"):
    txt = txt.split("```", 2)[1].split("\n", 1)[1]
display = json.loads(txt)
usage = resp.get("usage") or {}
out = {
    "model": MODEL,
    "usage": usage,
    "cost_usd": (usage.get("cost_details") or {}).get("upstream_inference_cost"),
    "elapsed_s": resp.get("_elapsed_s"),
    "display": display,
}
json.dump(out, open("layer2_display.json", "w"), indent=2)

print(f"model={MODEL}  elapsed={resp.get('_elapsed_s')}s")
print(
    f"  tokens: prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} "
    f"cached={(usage.get('prompt_tokens_details') or {}).get('cached_tokens')}"
)
print(f"  COST (upstream_inference_cost): ${out['cost_usd']}")
print(f"\naccountSummary:\n  {display.get('accountSummary')}")
print("\nwhyNow:")
for w in display.get("whyNow") or []:
    print(f"  * {w.get('headline')}\n      “{(w.get('quote') or '')[:150]}”  — {w.get('sourceDomain')}")
print("\ninsightLabels:")
for i in display.get("insightLabels") or []:
    print(f"  P{i.get('priority')} {i.get('fieldKey'):34s} -> {i.get('label')}")
print("\ncontacts:")
for c in display.get("contacts") or []:
    print(f"\n  == {c.get('name')} | {c.get('roleLabel')}")
    print(f"     {c.get('overview')}")
    for h in c.get("howToOpen") or []:
        print(f"     - “{h.get('line')}”\n         hook: {h.get('hook')}\n         {h.get('sourceUrl')}")
print("\nTOTAL:", C.total_spend())
