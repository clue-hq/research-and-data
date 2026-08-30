"""Step 9d — the same intent extractor, ONE SUBJECT PER CALL.

Passes 1, 2 and 3 all batched five subjects into one call and all three under-harvested: pass 3 —
whose entire charter was "pull the buying-intent quotes" — returned 4 rows, all four for the FIRST
subject, and stopped (604 completion tokens). That is a fan-out failure, not a capability failure.

This step re-runs the identical extractor with one person's report per call, to measure the
difference. It is the same experiment the platform's own architecture already bets on:
"orchestrator/worker per account with a bounded recursion knob ... workers return references".
"""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

ENTITIES = {
    "eliadis": "contact:george-eliadis",
    "hoffman": "contact:mark-hoffman",
    "blumberg": "contact:kate-blumberg",
    "churba": "contact:aaron-churba",
    "zhang": "contact:lewis-zhang",
}

SYSTEM = open("structuring_bundle_intent.txt").read().split("\n\n=====\n\n")[0]

all_rows = []
costs = []
for key, ent in ENTITIES.items():
    label = f"structure_intent_{key}"
    if "--from-cache" in sys.argv:
        resp = json.load(open(f"raw/{label}.json"))
    else:
        resp = C.openrouter(
            "openai/gpt-5-mini",
            [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": f"# ENTITY {ent}\n" + open(f"person_report_{key}.md").read(),
                },
            ],
            label=label,
            response_format={"type": "json_object"},
            timeout=600,
            reasoning={"effort": "minimal"},
        )
    parsed = json.loads(((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    rows = parsed.get("contact_claims") or []
    for r in rows:
        r["entity"] = ent  # the call knows its subject; never trust the model for entity routing
    all_rows += rows
    cost = ((resp.get("usage") or {}).get("cost_details") or {}).get("upstream_inference_cost")
    costs.append({"key": key, "rows": len(rows), "cost_usd": cost})
    print(f"  {ent}: {len(rows)} rows  ${cost}")
    for r in rows:
        print(f"      {json.dumps(r.get('value_json'))[:180]}")

C.save_raw("structure_intent_perperson_parsed", {"contact_claims": all_rows})
json.dump(costs, open("intent_loop_costs.json", "w"), indent=2)
print(
    f"\nper-person loop: {len(all_rows)} rows total vs 4 from the batched call; "
    f"cost ${round(sum(c['cost_usd'] or 0 for c in costs), 5)}"
)
print("TOTAL:", C.total_spend())
