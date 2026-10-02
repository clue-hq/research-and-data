"""Step 10 — conformance check: would `check_claim_writable` accept each registered-field claim?

The claim rows carry the right *stamps* (step 9) but nothing has yet checked each value against the
field's declared `value_schema`. That is exactly what `claimstore/registry.py::check_claim_writable`
does before insert, so running it here shows precisely which rows a production `write_claims` call
would refuse — and therefore how much value coercion the cheap structuring model still needs.

Declared schemas copied verbatim from the schema-authority branch.
"""

import json
import os
from collections import Counter

from clue_lib import HERE

VALUE_SCHEMA = {
    "core.account_name": {"type": "string"},
    "core.employee_count": {"type": "integer"},
    "core.primary_domain": {"type": "string"},
    "core.company_linkedin_url": {"type": "string"},
    "core.industry": {"type": "string"},
    "core.company_about": {"type": "string"},
    "core.company_email": {"type": "string"},
    "core.company_phone": {"type": "string"},
    "core.work_email": {"type": "string"},
    "core.direct_phone": {"type": "string"},
    "core.primary_tech_stack": {"type": "array", "items": {"type": "string"}},
    "core.employee_range": {"type": "object", "required": ["label"]},
    "core.hq_location": {"type": "object", "required": ["raw"]},
    "core.annual_revenue": {"type": "object"},
    "core.revenue_band": {"type": "object"},
    "account.operational_pain": {"type": "string"},
    "account.strategic_moves": {"type": "string"},
    "account.hiring_velocity_eng": {"type": "number"},
    "account.recent_funding": {"type": "object", "required": ["amount_usd"]},
    "account.total_funding": {"type": "object", "required": ["amount_usd", "estimate_kind"]},
    "account.resonance.culture": {"type": "string"},
    "account.resonance.buying_culture": {"type": "object", "required": ["culture_label"]},
    "account.resonance.employee_sentiment": {"type": "object", "required": ["label"]},
    "account.resonance.public_frustrations": {"type": "array"},
    "healthcare.npi": {"type": "string"},
    "contact.current_title": {"type": "string"},
    "contact.job_function": {"type": "string"},
    "contact.job_level": {"type": "string"},
    "contact.current_location": {"type": "object"},
    "contact.organization_relationship": {
        "type": "object",
        "required": ["relationship", "basis", "organization_id"],
        "enums": {
            "relationship": ["current_employee"],
            "basis": [
                "provider_returned_current_employer",
                "provider_inferred_team_membership",
            ],
        },
    },
    "contact.persona": {
        "type": "string",
        "enum": ["champion", "economic_buyer", "technical_evaluator", "blocker"],
    },
    "contact.role_on_committee": {
        "type": "object",
        "required": ["role"],
        "enums": {"role": ["champion", "economic_buyer", "technical_evaluator", "blocker"]},
        "numbers": ["confidence"],
        "booleans": ["plausible"],
    },
    "contact.class": {"type": "string"},
    "contact.facet.nickname": {"type": "string"},
    "contact.facet.stated_interests": {"type": "array", "items": {"type": "string"}},
    "contact.facet.communication_style": {"type": "object", "required": ["style_label"]},
    "contact.facet.public_appearances": {"type": "array", "items_required": ["title"]},
    "contact.facet.publications": {"type": "array", "items_required": ["title"]},
    "contact.facet.causes": {"type": "array", "items_required": ["cause"]},
    "contact.facet.alma_mater": {"type": "array", "items": {"type": "string"}},
    "contact.facet.career_history": {"type": "array", "items_required": ["org"]},
    "contact.facet.recent_post": {"type": "string"},
}

TYPE_OK = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "boolean": lambda v: isinstance(v, bool),
}


def check(field_key, value):
    schema = VALUE_SCHEMA.get(field_key)
    if schema is None:
        return None  # proposed field: no declared schema yet
    problems = []
    want = schema["type"]
    if not TYPE_OK[want](value):
        return [f"declared {want}, got {type(value).__name__}"]
    if want == "string" and schema.get("enum") and value not in schema["enum"]:
        problems.append(f"value {value!r} not in enum {schema['enum']}")
    if want == "object":
        for req in schema.get("required", []):
            if req not in value:
                problems.append(f"missing required property '{req}'")
        for prop, allowed in (schema.get("enums") or {}).items():
            if prop in value and value[prop] not in allowed:
                problems.append(f"'{prop}'={value[prop]!r} not in enum {allowed}")
        for prop in schema.get("numbers", []):
            if prop in value and not TYPE_OK["number"](value[prop]):
                problems.append(f"'{prop}' declared number, got {type(value[prop]).__name__}")
        for prop in schema.get("booleans", []):
            if prop in value and not isinstance(value[prop], bool):
                problems.append(f"'{prop}' declared boolean, got {type(value[prop]).__name__}")
    if want == "array":
        item_type = (schema.get("items") or {}).get("type")
        for i, item in enumerate(value):
            if item_type and not TYPE_OK[item_type](item):
                problems.append(f"item[{i}] declared {item_type}, got {type(item).__name__}")
            for req in schema.get("items_required", []):
                if isinstance(item, dict) and req not in item:
                    problems.append(f"item[{i}] missing required '{req}'")
    return problems


claims = json.load(open(os.path.join(HERE, "claims.json")))
report = []
for c in claims:
    if c["field_status"] != "registered":
        continue
    problems = check(c["field_key"], c["value_json"])
    if problems:
        report.append(
            {
                "field_key": c["field_key"],
                "entity": c["entity"],
                "value_json": c["value_json"],
                "problems": problems,
            }
        )

registered = [c for c in claims if c["field_status"] == "registered"]
print(f"registered-field claims checked: {len(registered)}")
print(f"would be REFUSED by check_claim_writable: {len(report)}")
for r in report:
    print(f"  - {r['field_key']}: {r['problems']}")
    print(f"      value: {json.dumps(r['value_json'], ensure_ascii=False)[:220]}")

print("\nfacet governance stamps:")
for c in claims:
    if c["field_key"].startswith("contact.facet."):
        print(f"  {c['field_key']:38} binding={c['identity_binding']:7} use_class={c['use_class']}")

json.dump(report, open(os.path.join(HERE, "schema_conformance_report.json"), "w"), indent=2)
print("\nby status:", dict(Counter(c["field_status"] for c in claims)))
