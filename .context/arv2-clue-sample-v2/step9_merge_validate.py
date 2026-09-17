"""Step 9 — merge the lanes into claims.json, validate every row against its value_schema, and
emit the counts the report needs. No network calls, no spend.

The merged set is the UNION of the two structuring runs (deduped), because the measured comparison
showed neither cheap model dominated: gpt-5-mini@minimal had the better breadth-per-dollar and
format compliance, glm-4.7 had the better semantic judgement on persona/committee/resonance. Each
row therefore carries `structuring_model` - the structuring step is itself provenance.
"""

import json
from collections import Counter, defaultdict

from field_catalog import ACCOUNT_FIELDS, CONTACT_FIELDS, FACET_FIELDS

SCHEMAS = {}
for k, (_vt, vs, _d) in ACCOUNT_FIELDS.items():
    SCHEMAS[k] = vs
for k, (_vt, vs, _d) in CONTACT_FIELDS.items():
    SCHEMAS[k] = vs
for k, (_vt, vs, _d, _uc) in FACET_FIELDS.items():
    SCHEMAS[k] = vs


def validate(value, schema, path="value"):
    """Minimal JSON-schema check covering the subset the registry actually uses."""
    errs = []
    t = schema.get("type")
    if t == "string":
        if not isinstance(value, str):
            errs.append(f"{path}: expected string, got {type(value).__name__}")
        elif schema.get("enum") and value not in schema["enum"]:
            errs.append(f"{path}: {value!r} not in enum {schema['enum']}")
    elif t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errs.append(f"{path}: expected integer, got {type(value).__name__}")
    elif t == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errs.append(f"{path}: expected number, got {type(value).__name__}")
    elif t == "array":
        if not isinstance(value, list):
            errs.append(f"{path}: expected array, got {type(value).__name__}")
        else:
            for i, item in enumerate(value):
                errs += validate(item, schema.get("items") or {}, f"{path}[{i}]")
    elif t == "object":
        if not isinstance(value, dict):
            errs.append(f"{path}: expected object, got {type(value).__name__}")
        else:
            for req in schema.get("required") or []:
                if req not in value or value[req] is None:
                    errs.append(f"{path}: missing required property {req!r}")
            for pk, pv in (schema.get("properties") or {}).items():
                if pk in value and value[pk] is not None:
                    errs += validate(value[pk], pv, f"{path}.{pk}")
    return errs


apollo_claims = json.load(open("raw/claims_apollo.json"))
for c in apollo_claims:
    c["structuring_model"] = "deterministic-adapter"

RUNS = [
    ("raw/structure_openai_gpt-5-mini_reason_minimal_parsed.json", "openai/gpt-5-mini@minimal"),
    ("raw/structure_z-ai_glm-4_7_parsed.json", "z-ai/glm-4.7"),
]

merged = list(apollo_claims)
seen = {(c["entity"], c["field_key"], json.dumps(c["value_json"], sort_keys=True)) for c in merged}
per_model = Counter()
for path, tag in RUNS:
    for c in json.load(open(path))["claims"]:
        key = (c["entity"], c["field_key"], json.dumps(c["value_json"], sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        c["structuring_model"] = tag
        merged.append(c)
        per_model[tag] += 1

# --- validation -------------------------------------------------------------
invalid = []
for c in merged:
    errs = validate(c["value_json"], SCHEMAS[c["field_key"]])
    if not c.get("source_url"):
        errs.append("missing source_url")
    if c["field_key"].startswith("contact.facet.") and not c.get("use_class"):
        errs.append("facet claim missing use_class")
    if c["field_key"].startswith("contact.") and not c.get("identity_binding"):
        errs.append("contact claim missing identity_binding")
    if c["source_tier"] == 4 and c["extraction_method"] != "llm_synthesis":
        errs.append("tier4 must be llm_synthesis (claim_tier4_iff_synthesis)")
    if c["source_tier"] != 4 and c["extraction_method"] == "llm_synthesis":
        errs.append("llm_synthesis must be tier4 (claim_tier4_iff_synthesis)")
    if c["reuse_scope"] == "public_footprint" and c.get("workspace_id"):
        errs.append("public_footprint requires NULL workspace_id")
    if errs:
        c["_validation_errors"] = errs
        invalid.append({"field_key": c["field_key"], "entity": c["entity"],
                        "model": c["structuring_model"], "errors": errs})

json.dump(merged, open("claims.json", "w"), indent=2)

# --- known semantic defects a schema validator CANNOT catch (hand-audited) ---
semantic_defects = [
    {
        "row": "core.company_linkedin_url (openai/gpt-5-mini@minimal)",
        "emitted": "https://www.lassie.ai/company",
        "problem": "not a LinkedIn URL. Passes value_schema (any string) but is semantically wrong."
                   " Apollo's tier-1 row carries the correct http://www.linkedin.com/company/lassie.",
        "catchable_by": "a tool-side format/host validator on url-shaped fields, not value_schema",
    },
    {
        "row": "contact.persona = champion for Steijn Pelle (openai/gpt-5-mini@minimal)",
        "emitted": "champion",
        "problem": "Steijn Pelle is the CEO/co-founder = economic_buyer. The evidence_span cited is"
                   " an interview-process sentence from a job posting and does not support any"
                   " persona. glm-4.7 assigned economic_buyer correctly.",
        "catchable_by": "the faithfulness judge (M9.3) - the span does not entail the value",
    },
    {
        "row": "core.employee_count = 23 (openai/gpt-5-mini, default reasoning run)",
        "emitted": 23,
        "problem": "the account report explicitly flagged 23 as an unreliable aggregator estimate;"
                   " Apollo's tier-1 value is 41. Not carried into the merged set.",
        "catchable_by": "tier precedence in the merge policy (tier-1 apollo beats tier-4 synthesis)",
    },
]

by_field = Counter(c["field_key"] for c in merged)
by_tier = Counter(c["source_tier"] for c in merged)
by_entity = Counter(c["entity"] for c in merged)
by_source = Counter(c["source_key"] for c in merged)

proposed = {}
for path, tag in RUNS:
    for p in json.load(open(path))["proposed_fields"]:
        proposed.setdefault(p["field_key"], {"proposed_by": [], **p})["proposed_by"].append(tag)

summary = {
    "total_claims": len(merged),
    "by_source_key": dict(by_source),
    "by_tier": {str(k): v for k, v in by_tier.items()},
    "by_entity": dict(by_entity),
    "by_field_key": dict(sorted(by_field.items())),
    "distinct_field_keys": len(by_field),
    "all_field_keys_registered": True,
    "rows_contributed_by_structuring_model": dict(per_model),
    "schema_validation_failures": invalid,
    "semantic_defects_hand_audited": semantic_defects,
    "model_proposed_fields": list(proposed.values()),
}
json.dump(summary, open("claims_summary.json", "w"), indent=2)

print("merged claims:", len(merged))
print("  by source_key:", dict(by_source))
print("  by tier:", dict(by_tier))
print("  by entity:", dict(by_entity))
print("  distinct field_keys:", len(by_field))
print("  rows per structuring model:", dict(per_model))
print("  schema validation failures:", len(invalid))
for i in invalid:
    print("    !", i["entity"], i["field_key"], i["model"], i["errors"])
print("  model-proposed fields:", list(proposed))
print("\nby field_key:")
for k, v in sorted(by_field.items()):
    print(f"    {k:42s} {v}")
