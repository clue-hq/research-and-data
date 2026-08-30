"""Step 9 — stamp, validate and dedupe the structured rows into final claims.json.

Stamping is done HERE in code, never by the model, exactly per ARV2-schema-impact-audit.md §3:
  origin=apollo    -> source_key=apollo,       source_tier=1, extraction_method=api
  origin=exa_deep  -> source_key=exa_research,  source_tier=4, extraction_method=llm_synthesis
  origin=exa_cheap -> source_key=exa_search,    source_tier=4, extraction_method=llm_synthesis
Every row: claim_flavor=field_claim, verification_status=unverified, reuse_scope=tenant_private
(+ workspace_id in production). contact.facet.* rows additionally carry identity_binding +
use_class, and are refused here if either is missing — the same refusal `write_claims` performs
before the DB CHECK `claim_contact_field_requires_governance` could fire.
"""

import json
import os
from collections import Counter

from clue_lib import HERE

# The registered field keys, verbatim from the schema-authority branch (see step8_structure.py).
REGISTERED = {
    "core.account_name", "core.employee_count", "core.primary_domain", "core.company_linkedin_url",
    "core.industry", "core.company_about", "core.employee_range", "core.hq_location",
    "core.annual_revenue", "core.revenue_band", "core.company_email", "core.company_phone",
    "core.work_email", "core.direct_phone", "core.primary_tech_stack",
    "account.recent_funding", "account.total_funding", "account.crm_relationship_status",
    "account.scoring.fit", "account.scoring.intent", "account.scoring.tier",
    "account.hiring_velocity_eng", "account.operational_pain", "account.strategic_moves",
    "account.resonance.culture", "account.resonance.research_prestige",
    "account.resonance.employee_sentiment", "account.resonance.attrition_signal",
    "account.resonance.eng_blog_tone", "account.resonance.public_frustrations",
    "account.resonance.buying_culture",
    "healthcare.npi",
    "contact.current_title", "contact.job_function", "contact.job_level",
    "contact.team_membership", "contact.current_location", "contact.organization_relationship",
    "contact.role_on_committee", "contact.persona", "contact.class",
    "contact.facet.nickname", "contact.facet.stated_interests", "contact.facet.communication_style",
    "contact.facet.public_appearances", "contact.facet.publications", "contact.facet.causes",
    "contact.facet.alma_mater", "contact.facet.career_history", "contact.facet.recent_post",
}

STAMP = {
    "apollo": ("apollo", 1, "api"),
    "exa_deep": ("exa_research", 4, "llm_synthesis"),
    "exa_cheap": ("exa_search", 4, "llm_synthesis"),
}

raw = json.load(open(os.path.join(HERE, "structured_raw.json")))
rows_in = raw["claims"]
proposed_in = {p["field_key"]: p for p in raw["proposed_fields"] if p.get("field_key")}

# Round-2's single-call GLM run carried proposed-field definitions the chunked contact pass
# omitted; fold in any it defined for a key the chunked run actually used.
r2 = json.load(open(os.path.join(HERE, "raw", "step8b_z-ai_glm-47_parsed.json")))
for p in r2.get("proposed_fields") or []:
    proposed_in.setdefault(p.get("field_key"), p)

out, rejected = [], []
seen = set()
for r in rows_in:
    fk = (r.get("field_key") or "").strip()
    entity = (r.get("entity") or "").strip()
    origin = r.get("origin") or "exa_deep"
    if origin not in STAMP:
        origin = "exa_deep"
    src, tier, method = STAMP[origin]

    if not fk or not entity:
        rejected.append({"row": r, "reason": "missing field_key or entity"})
        continue
    if not r.get("source_url"):
        rejected.append({"row": r, "reason": "missing source_url (_URL_REQUIRED_METHODS)"})
        continue
    # The chunked account pass emitted the value under `value_` rather than `value_json` — a
    # model key-name slip, tolerated here (and worth a schema-locked tool signature in production).
    value = next(
        (r[k] for k in ("value_json", "value_", "value") if r.get(k) not in (None, "", [], {})),
        None,
    )
    if value in (None, "", [], {}):
        rejected.append({"row": r, "reason": "empty value_json"})
        continue
    r = dict(r, value_json=value)

    registered = fk in REGISTERED
    claim = {
        "entity": entity,
        "entity_type": "account" if entity.startswith("account:") else "contact",
        "field_key": fk,
        "field_status": "registered" if registered else "proposed",
        "claim_flavor": "field_claim",
        "value_json": r.get("value_json"),
        "evidence_span": (r.get("evidence_span") or "")[:400],
        "source_url": r["source_url"],
        "source_key": src,
        "source_tier": tier,
        "extraction_method": method,
        "verification_status": "unverified",
        "reuse_scope": "tenant_private",
    }
    if fk.startswith("contact.facet."):
        binding = r.get("identity_binding")
        use_class = r.get("use_class")
        if binding not in ("strong", "weak") or use_class not in (
            "professional-public",
            "personal-public-non-sensitive",
            "sensitive",
        ):
            rejected.append(
                {
                    "row": r,
                    "reason": "contact.facet.* requires identity_binding + use_class "
                    "(claim_contact_field_requires_governance)",
                }
            )
            continue
        claim["identity_binding"] = binding
        claim["use_class"] = use_class
    elif claim["entity_type"] == "contact":
        # Plain contact.* / core.* contact facts are professional-public committee facts; the
        # facet CHECK does not bind them, but the committee pack stamps them anyway.
        claim["identity_binding"] = r.get("identity_binding") or "strong"
        claim["use_class"] = "professional-public"

    key = (entity, fk, json.dumps(claim["value_json"], sort_keys=True)[:300], claim["source_url"])
    if key in seen:
        rejected.append({"row": r, "reason": "duplicate (entity, field, value, url)"})
        continue
    seen.add(key)
    out.append(claim)

json.dump(out, open(os.path.join(HERE, "claims.json"), "w"), indent=2)

used_proposed = sorted({c["field_key"] for c in out if c["field_status"] == "proposed"})
proposed_final = []
for fk in used_proposed:
    p = proposed_in.get(fk)
    if p:
        proposed_final.append(p)
    else:
        proposed_final.append(
            {
                "field_key": fk,
                "entity_type": "contact" if fk.startswith("contact") else "account",
                "value_type": "str",
                "value_schema": {"type": "string"},
                "description": "(definition not emitted by the structuring pass)",
                "reuse_scope": "tenant_private",
                "why_needed": "(definition not emitted by the structuring pass)",
            }
        )
json.dump(proposed_final, open(os.path.join(HERE, "proposed_fields.json"), "w"), indent=2)

print(f"CLAIMS accepted: {len(out)}   rejected: {len(rejected)}")
print("  by entity:", dict(Counter(c["entity"] for c in out)))
print("  by field_status:", dict(Counter(c["field_status"] for c in out)))
print("  by source_key:", dict(Counter(c["source_key"] for c in out)))
print("  by tier:", dict(Counter(c["source_tier"] for c in out)))
print(f"  registered keys used: {len({c['field_key'] for c in out if c['field_status']=='registered'})}")
print(f"  proposed keys used:   {len(used_proposed)}")
print("  with evidence_span:", sum(1 for c in out if c["evidence_span"]))
if rejected:
    print("REJECTIONS:")
    for x in rejected:
        print("   -", x["reason"], "|", (x["row"].get("field_key"), x["row"].get("entity")))
json.dump(rejected, open(os.path.join(HERE, "claims_rejected.json"), "w"), indent=2)
print("\nFIELD KEY COUNTS")
for k, v in sorted(Counter(c["field_key"] for c in out).items()):
    star = "" if k in REGISTERED else "   <-- PROPOSED"
    print(f"  {v:3}  {k}{star}")
