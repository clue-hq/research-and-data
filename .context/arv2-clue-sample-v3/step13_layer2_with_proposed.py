"""Step 13 — Layer 2, run a SECOND time against the payload WITH the proposed slots filled.

Run A (step12) fed Luna the as-built payload. Its "Why now" card came back weak — it led with the
funding round and then reached for `core.primary_tech_stack` ("broad enough to anchor a stack
conversation"), because the as-built account payload physically cannot express:
  * the six open GTM reqs and what they say,
  * the ABSENCE of a CRM / outbound / ABM stack (a flat `list[str]` cannot encode absence),
  * the champion's own public evaluation of ABM list-building tools (a CONTACT claim, and the
    account payload never sees contact claims).

Run B feeds the identical model the identical prompt over a payload where `topSignals[]`,
`neutralFacts[].priority` and a project_relative `vertical_saas.*` pack exist. The delta between
the two cards IS the value of the proposed slots, measured rather than argued.
"""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

MODEL = "openai/gpt-5.6-luna"
p = json.load(open("layer1_payloads.json"))
claims = json.load(open("claims.json"))
detail = json.loads(json.dumps(p["GET /frontend/v1/accounts/{accountId}"]))
slots = p["_PROPOSED_SLOTS"]

prio = {r["fieldKey"]: r["priority"] for r in slots["account.neutralFacts[].priority"]["example"]}
for f in detail["neutralFacts"]:
    f["priority"] = prio.get(f["fieldKey"])

detail["projectSections"][0]["insights"] = slots[
    "projectSections[].insights[] — needs a project_relative pack"
]["example_if_pack_registered"]

# topSignals[] as PROPOSED: account P1s + the committee's own P1 statements + the pack signals.
# The account view's "why now" must be able to reach a CONTACT-level signal; today it cannot.
top = list(slots["account.topSignals[]"]["example"])
for c in claims:
    if c["priority"] == 1 and c["entity"].startswith("contact:"):
        top.append(
            {
                "entityId": c["entity"],
                "personName": c["entity"].split(":")[1].replace("-", " ").title(),
                "fieldKey": c["field_key"],
                "quote": c["evidence_span"],
                "sourceDomain": (c["source_url"] or "").split("/")[2] if c["source_url"] else None,
                "observedAt": detail["neutralFacts"][0]["observedAt"],
            }
        )
top.append(
    {
        "fieldKey": "vertical_saas.gtm_stack",
        "quote": "current_technologies (30 detected): no CRM, no sales-engagement tool, no data "
        "provider and no ABM/intent platform are present; LinkedIn Ads and LinkedIn Recruiter "
        "are the only GTM tools detected",
        "sourceDomain": "apollo.io",
        "observedAt": detail["neutralFacts"][0]["observedAt"],
    }
)
top.append(
    {
        "fieldKey": "vertical_saas.open_gtm_roles",
        "quote": "We have a clearly defined target: the top home service operators in America. "
        "The list exists. The product is proven. What we need now is someone to go get them.",
        "sourceDomain": "jobs.ashbyhq.com",
        "observedAt": detail["neutralFacts"][0]["observedAt"],
    }
)
detail["topSignals"] = top

payloads_b = {
    "_variant": "PROPOSED — the same account with priority, topSignals[] and a project_relative "
    "vertical_saas.* pack registered. Every other shape is byte-identical to the as-built payload.",
    "GET /frontend/v1/accounts": p["GET /frontend/v1/accounts"],
    "GET /frontend/v1/accounts/{accountId}": detail,
    "GET /frontend/v1/accounts/{accountId}/contacts": p["GET /frontend/v1/accounts/{accountId}/contacts"],
    "GET /frontend/v1/accounts/{accountId}/contacts/{contactId}": p[
        "GET /frontend/v1/accounts/{accountId}/contacts/{contactId}"
    ],
    "_PROPOSED_SLOTS": {
        "contact.professionalFacts — missing families": slots[
            "contact.professionalFacts — missing families"
        ],
        "contact.openers[]": slots["contact.openers[]"],
    },
}
json.dump(payloads_b, open("layer1_payloads_proposed.json", "w"), indent=2)

SYSTEM = open("step12_layer2_luna.py").read().split('SYSTEM = """')[1].split('"""')[0]
USER = (
    "# THE BACKEND PAYLOADS (this is everything you know)\n\n```json\n"
    + json.dumps(payloads_b, indent=1)
    + "\n```\n\nProduce the display layer now."
)

resp = C.openrouter(
    MODEL,
    [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
    label="layer2_luna_proposed",
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
    "variant": "proposed-slots",
    "usage": usage,
    "cost_usd": (usage.get("cost_details") or {}).get("upstream_inference_cost"),
    "elapsed_s": resp.get("_elapsed_s"),
    "display": display,
}
json.dump(out, open("layer2_display_proposed.json", "w"), indent=2)

print(f"tokens prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')}")
print(f"COST: ${out['cost_usd']}  elapsed={resp.get('_elapsed_s')}s")
print(f"\naccountSummary:\n  {display.get('accountSummary')}\n")
print("whyNow (PROPOSED variant):")
for w in display.get("whyNow") or []:
    print(f"  * {w.get('headline')}\n      “{(w.get('quote') or '')[:200]}”  — {w.get('sourceDomain')}")
print("\nTOTAL:", C.total_spend())
