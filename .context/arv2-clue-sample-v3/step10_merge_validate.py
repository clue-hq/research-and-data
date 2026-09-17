"""Step 10 — merge both lanes into claims.json, validate every row, emit counts + the v3 priority
histogram. No network calls, no spend."""

import json
import sys
from collections import Counter, defaultdict

# OPERATOR ERROR, recorded: the first run of this file imported `step9_structure` WITHOUT this
# flag, and step9's module-level body re-executed both OpenRouter structuring calls — an accidental
# $0.01682 re-spend, in the ledger as the second `structure_account`/`structure_contacts` rows.
# The flag puts step9 in cache mode so the import is free.
if "--from-cache" not in sys.argv:
    sys.argv.append("--from-cache")

from field_catalog import ACCOUNT_FIELDS, CONTACT_FIELDS, FACET_FIELDS  # noqa: E402

SCHEMAS = {}
for k, (_vt, vs, _d) in ACCOUNT_FIELDS.items():
    SCHEMAS[k] = vs
for k, (_vt, vs, _d) in CONTACT_FIELDS.items():
    SCHEMAS[k] = vs
for k, (_vt, vs, _d, _uc) in FACET_FIELDS.items():
    SCHEMAS[k] = vs


def validate(value, schema, path="value"):
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
        if not isinstance(value, int | float) or isinstance(value, bool):
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

parsed = json.load(open("raw/structure_parsed.json"))
merged = list(apollo_claims)
seen = {(c["entity"], c["field_key"], json.dumps(c["value_json"], sort_keys=True)) for c in merged}
dupes = 0
per_pass = Counter()


def take(rows, pass_tag, default_entity=None):
    """Absorb one structuring pass's rows, deduping on (entity, field_key, value)."""
    global dupes
    import step9_structure as S  # reuse the same stamp/validation helpers, never a second copy

    for row in rows or []:
        fk = row.get("field_key")
        if fk not in SCHEMAS:
            continue
        ent = row.get("entity") or default_entity
        if ent not in ({"account:probook"} | set(S.ENTITY_OF.values())):
            continue
        v = row.get("value_json")
        # Rule violations the sweep produced: a literal "NOT FOUND" value and an empty list.
        if v == "NOT FOUND" or v == [] or v is None:
            continue
        if not row.get("source_url"):
            continue
        c = S.stamp(
            row,
            source_key="exa_research",
            tier=4,
            method="llm_synthesis",
            source_url=row["source_url"],
            entity=ent,
            priority_default=3,
        )
        key = (c["entity"], c["field_key"], json.dumps(c["value_json"], sort_keys=True))
        if key in seen:
            dupes += 1
            continue
        seen.add(key)
        c["structuring_model"] = "openai/gpt-5-mini@minimal"
        c["structuring_pass"] = pass_tag
        merged.append(c)
        per_pass[pass_tag] += 1


for c in parsed["claims"]:
    key = (c["entity"], c["field_key"], json.dumps(c["value_json"], sort_keys=True))
    if key in seen:
        dupes += 1
        continue
    seen.add(key)
    c["structuring_model"] = parsed["model"] + "@minimal"
    c["structuring_pass"] = "p1_broad_extraction"
    merged.append(c)
    per_pass["p1_broad_extraction"] += 1

sweep = json.load(open("raw/structure_p1_sweep_parsed.json"))
take(sweep.get("contact_claims"), "p2_priority_sweep")
take(sweep.get("account_claims"), "p2_priority_sweep", default_entity="account:probook")
take(
    json.load(open("raw/structure_intent_perperson_parsed.json")).get("contact_claims"),
    "p4_intent_extractor_per_person",
)
for c in apollo_claims:
    c.setdefault("structuring_pass", "p0_deterministic_apollo_adapter")

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
        errs.append("tier 4 must be llm_synthesis (tier-4-iff-synthesis CHECK)")
    if c["source_tier"] != 4 and c["extraction_method"] == "llm_synthesis":
        errs.append("llm_synthesis must be tier 4")
    if c.get("priority") not in (1, 2, 3):
        errs.append("missing/invalid priority annotation")
    if errs:
        invalid.append({"entity": c["entity"], "field_key": c["field_key"], "errors": errs})

by_entity = Counter(c["entity"] for c in merged)
by_tier = Counter(c["source_tier"] for c in merged)
by_source = Counter(c["source_key"] for c in merged)
by_priority = Counter(c["priority"] for c in merged)
prio_by_entity = defaultdict(Counter)
for c in merged:
    prio_by_entity[c["entity"]][c["priority"]] += 1
fields_used = sorted({c["field_key"] for c in merged})
account_fields_used = sorted({c["field_key"] for c in merged if c["entity"].startswith("account:")})
empty_registered = sorted(set(ACCOUNT_FIELDS) - set(account_fields_used))

json.dump(merged, open("claims.json", "w"), indent=2)
summary = {
    "total_claims": len(merged),
    "deduped_against_apollo_lane": dupes,
    "by_entity": dict(by_entity),
    "by_source_tier": {str(k): v for k, v in sorted(by_tier.items())},
    "by_source_key": dict(by_source),
    "priority_histogram": {str(k): v for k, v in sorted(by_priority.items())},
    "priority_by_entity": {k: {str(p): n for p, n in sorted(v.items())} for k, v in prio_by_entity.items()},
    "distinct_fields_used": len(fields_used),
    "fields_used": fields_used,
    "registered_account_fields_left_empty": empty_registered,
    "schema_validation": {"checked": len(merged), "invalid": len(invalid), "details": invalid},
    "structuring_defects": parsed["defects"],
    "claims_by_structuring_pass": dict(per_pass),
    "model_proposed_fields": parsed["proposed_fields"],
}
json.dump(summary, open("claims_summary.json", "w"), indent=2)

print(f"claims: {len(merged)}  (deduped {dupes})")
print("by entity:", dict(by_entity))
print("by tier:", dict(by_tier))
print("priority histogram:", dict(sorted(by_priority.items())))
print("distinct fields:", len(fields_used))
print("registered account fields left EMPTY:", empty_registered)
print(f"schema validation: {len(merged) - len(invalid)}/{len(merged)} valid")
for i in invalid:
    print("   INVALID", i["entity"], i["field_key"], i["errors"])
