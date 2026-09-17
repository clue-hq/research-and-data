"""Step 8 — the structuring pass.

Two lanes, deliberately separated because the stamping matrix separates them:

  A. APOLLO -> tier 1 / `api` / source_key `apollo`. Adapter-normalized, so these rows are built
     DETERMINISTICALLY in Python. A model must never author a tier-1 claim: the tier-4-iff-synthesis
     CHECK means anything a model writes is tier 4 by construction.
  B. EXA REPORTS -> tier 4 / `llm_synthesis` / source_key `exa_research`. A cheap OpenRouter model
     reads the two free-form deep reports and emits value + verbatim evidence_span + source_url per
     registered field key. The provenance stamp is applied in Python afterwards, never by the model.

Run:  python3 step8_structure.py <model>     (default z-ai/glm-4.7)
"""

import json
import sys

from clue_lib import openrouter, save_raw, total_spend
from field_catalog import ACCOUNT_FIELDS, CONTACT_FIELDS, FACET_FIELDS, catalog_text

ACCOUNT = "account:lassie"
CONTACT = "contact:steijn-pelle"
WS = "workspace:clue-sample"
APOLLO_ORG_URL = "http://www.linkedin.com/company/lassie"


_CONF_WORDS = {"high": 0.85, "medium": 0.65, "med": 0.65, "low": 0.4}


def _value_of(row):
    """Tolerate model key drift. Observed: z-ai/glm-4.7 emits `value_` on EVERY row instead of the
    requested `value_json`; a real tool would refuse the item, but for the sample we repair and
    record the defect."""
    for key in ("value_json", "value_", "value"):
        if key in row:
            return row[key], key
    raise KeyError("no value key in row: " + json.dumps(row)[:200])


def _conf(raw, default):
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    if isinstance(raw, str):
        return _CONF_WORDS.get(raw.strip().lower(), default)
    return default


def stamp(row, *, source_key, tier, method, source_url, entity):
    """The fixed per-tool provenance stamp (schema-impact-audit §3). Never model-supplied."""
    value, _ = _value_of(row)
    out = {
        "entity": entity,
        "field_key": row["field_key"],
        "value_json": value,
        "evidence_span": (row.get("evidence_span") or "")[:600] or None,
        "source_url": source_url or row.get("source_url"),
        "source_key": source_key,
        "source_tier": tier,
        "extraction_method": method,
        "verification_status": "unverified",
        "claim_flavor": "field",
        "reuse_scope": "tenant_private",
        "workspace_id": WS,
        "confidence": _conf(row.get("confidence"), 0.9 if tier == 1 else 0.7),
    }
    if row["field_key"].startswith("contact."):
        out["identity_binding"] = row.get("identity_binding", "strong")
    if row["field_key"].startswith("contact.facet."):
        out["use_class"] = row.get("use_class") or FACET_FIELDS[row["field_key"]][3]
    return out


# ---------------------------------------------------------------- lane A: Apollo (deterministic)
org = json.load(open("raw/apollo_org_normalized.json"))
matched = json.load(open("raw/apollo_matched_contacts.json"))
primary = matched[0]

apollo_claims = []


def a(field_key, value, span, entity=ACCOUNT, url=APOLLO_ORG_URL, **kw):
    apollo_claims.append(
        stamp(
            {"field_key": field_key, "value_json": value, "evidence_span": span, **kw},
            source_key="apollo",
            tier=1,
            method="api",
            source_url=url,
            entity=entity,
        )
    )


a("core.account_name", org["name"], f'organization.name = "{org["name"]}"')
a("core.primary_domain", org["primary_domain"], f'primary_domain = "{org["primary_domain"]}"')
a("core.company_linkedin_url", org["linkedin_url"], f'linkedin_url = "{org["linkedin_url"]}"')
a("core.industry", org["industry"], f'industry = "{org["industry"]}"')
a("core.company_about", (org["short_description"] or "")[:1200], "organization.short_description")
a(
    "core.employee_count",
    org["estimated_num_employees"],
    f'estimated_num_employees = {org["estimated_num_employees"]}',
)
a(
    "core.hq_location",
    {
        "raw": org["raw_address"],
        "city": org["city"],
        "region": org["state"],
        "country": org["country"],
        "country_code": "US",
    },
    f'raw_address = "{org["raw_address"]}"',
)
a("core.company_phone", org["phone"], f'phone = "{org["phone"]}"')
a(
    "core.primary_tech_stack",
    org["technology_names"],
    f'technology_names ({len(org["technology_names"])} entries) incl. '
    + ", ".join(org["technology_names"][:8]),
)
fe = (org.get("funding_events") or [{}])[0]
a(
    "account.recent_funding",
    {"amount_usd": 35000000.0, "round": fe.get("type")},
    f'funding_events[0] = {{date: "{fe.get("date")}", type: "{fe.get("type")}", '
    f'amount: "{fe.get("amount")}", investors: "{fe.get("investors")}"}}',
    url=fe.get("news_url") or APOLLO_ORG_URL,
)
a(
    "account.total_funding",
    {"amount_usd": float(org["total_funding"]), "estimate_kind": "provider_estimate"},
    f'total_funding = {org["total_funding"]} ("{org["total_funding_printed"]}")',
)

# Contact rows from people/match (tier 1 api) — BOTH enriched committee members.
CONTACT_IDS = {"Steijn Pelle": CONTACT, "Max Shore": "contact:max-shore"}
for person in matched:
    ent = CONTACT_IDS[person["name"]]
    p_url = person["linkedin_url"]
    a("core.work_email", person["email"], f'email = "{person["email"]}" '
      f'(email_status = "{person["email_status"]}")', entity=ent, url=p_url)
    a("contact.current_title", person["title"], f'title = "{person["title"]}"',
      entity=ent, url=p_url)
    a(
        "contact.current_location",
        {"raw": f'{person["city"]}, {person["state"]}, {person["country"]}',
         "country": person["country"]},
        f'city/state/country = {person["city"]}/{person["state"]}/{person["country"]}',
        entity=ent,
        url=p_url,
    )
    a(
        "contact.facet.career_history",
        [
            {
                "org": h.get("organization_name"),
                "role": h.get("title"),
                "start": h.get("start_date"),
                "end": h.get("end_date") or "present",
            }
            for h in (person.get("employment_history") or [])
        ],
        "employment_history[] from Apollo people/match: "
        + "; ".join(
            f'{h.get("title")} @ {h.get("organization_name")} ({h.get("start_date")}..'
            f'{h.get("end_date") or "present"})'
            for h in (person.get("employment_history") or [])[:7]
        ),
        entity=ent,
        url=p_url,
    )

save_raw("claims_apollo", apollo_claims)
print(f"lane A (apollo, tier1/api): {len(apollo_claims)} claims")

# ---------------------------------------------------------------- lane B: Exa reports (LLM)
account_report = open("account_report.md").read()
contact_report = open("contact_report.md").read()
gap = json.load(open("raw/g1_seed_round.json"))
gap_text = "\n\n".join(
    f"SOURCE {it.get('url')}\n{(it.get('text') or '')[:2500]}" for it in (gap.get("results") or [])
)[:9000]
postings = json.load(open("raw/g2_ashby_postings.json"))
post_text = "\n\n".join(
    f"SOURCE {it.get('url')}\n{(it.get('text') or '')[:2500]}"
    for it in (postings.get("results") or [])
)[:14000]

SYSTEM = """You convert free-form research reports into typed claim rows for a claim store.

ABSOLUTE RULES
1. You may ONLY use a field_key from the catalog given to you. If a fact does not fit any catalog
   key, DO NOT force it - put it in proposed_fields instead.
2. value_json MUST validate against that field's value_schema exactly (right JSON type, required
   properties present, enum values exact).
3. evidence_span MUST be a VERBATIM substring of the report - copy the quoted text exactly as it
   appears. Never paraphrase into evidence_span. If the report gives no quote for a fact, omit the
   fact entirely.
4. source_url MUST be the URL the report attributes that fact to. Every row needs one. Never invent
   a URL, never reuse an unrelated one.
5. NEVER emit a row for anything the report marked "NOT FOUND" or "excluded: special-category".
6. Do not emit provenance fields (source_key, tier, extraction_method, verification_status): the
   caller stamps those. Emit only field_key, value_json, evidence_span, source_url, confidence, and
   for contact.facet.* also use_class.
7. Prefer fewer, well-evidenced rows over many thin ones. One row per field per distinct fact.

Return ONLY a JSON object: {"account_claims":[...], "contact_claims":[...], "proposed_fields":[...]}
Each claim: {"field_key","value_json","evidence_span","source_url","confidence"} (+ "use_class" for
contact.facet.*).
Each proposed field: {"field_key","entity_type","value_type","value_schema","description",
"reuse_scope","hypothesis","example_value","example_evidence_span","example_source_url"} where
description is agent-facing (what an agent reads to decide whether to fill it), reuse_scope is
"tenant_private" or "public_footprint", and hypothesis is one paragraph on why the platform needs
this field for an ABM ICP like this one."""

USER = f"""# FIELD CATALOG (the ONLY keys you may use)
{catalog_text()}

# ACCOUNT: Lassie (lassie.ai). Entity id: {ACCOUNT}
# CONTACT: Steijn Pelle, CEO & co-founder. Entity id: {CONTACT}

# REPORT 1 - ACCOUNT DEEP RESEARCH (Exa deep-reasoning)
{account_report}

# REPORT 2 - CONTACT DEEP RESEARCH (Exa deep-reasoning)
{contact_report}

# SUPPLEMENTARY SOURCE EXTRACTS - funding / analyst pages
{gap_text}

# SUPPLEMENTARY SOURCE EXTRACTS - the company's own job postings (jobs.ashbyhq.com/lassie)
{post_text}

Emit the claim rows now. Remember: verbatim evidence_span, real source_url, catalog keys only,
and route everything that does not fit into proposed_fields."""

model = sys.argv[1] if len(sys.argv) > 1 else "z-ai/glm-4.7"
label = "structure_" + model.replace("/", "_").replace(".", "_")
REASONING = None
if "--reasoning" in sys.argv:
    REASONING = json.loads(sys.argv[sys.argv.index("--reasoning") + 1])
    label += "_reason_" + (REASONING.get("effort") or str(REASONING.get("enabled")))
if "--from-cache" in sys.argv:
    resp = json.load(open(f"raw/{label}.json"))  # re-parse, no second spend
    print(f"  [cache] {model} elapsed={resp.get('_elapsed_s')}s")
else:
    resp = openrouter(
        model,
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        label=label,
        response_format={"type": "json_object"},
        timeout=900,
        reasoning=REASONING,
    )
open("structuring_bundle.txt", "w").write(SYSTEM + "\n\n=====\n\n" + USER)

txt = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
if txt.strip().startswith("```"):
    txt = txt.split("```", 2)[1].split("\n", 1)[1] if "```" in txt else txt
try:
    parsed = json.loads(txt)
except Exception as exc:  # noqa: BLE001
    print("PARSE FAILURE:", exc)
    print(txt[:1500])
    save_raw(label + "_unparsed", {"text": txt})
    sys.exit(1)

exa_claims = []
defects = {"wrong_value_key": 0, "string_confidence": 0, "unregistered_field": [],
           "missing_source_url": [], "unquoted_evidence": []}
for bucket, entity in (("account_claims", ACCOUNT), ("contact_claims", CONTACT)):
    for row in parsed.get(bucket) or []:
        fk = row.get("field_key")
        known = fk in ACCOUNT_FIELDS or fk in CONTACT_FIELDS or fk in FACET_FIELDS
        if not known:
            defects["unregistered_field"].append(fk)
            print("  DROPPED unregistered field_key:", fk)
            continue
        if not row.get("source_url"):
            defects["missing_source_url"].append(fk)
            print("  DROPPED missing source_url:", fk)
            continue
        _, used_key = _value_of(row)
        if used_key != "value_json":
            defects["wrong_value_key"] += 1
        if isinstance(row.get("confidence"), str):
            defects["string_confidence"] += 1
        span = row.get("evidence_span") or ""
        corpus = account_report + contact_report + gap_text + post_text
        if span and span[:60] not in corpus:
            defects["unquoted_evidence"].append(fk)
        exa_claims.append(
            stamp(row, source_key="exa_research", tier=4, method="llm_synthesis",
                  source_url=row.get("source_url"), entity=entity)
        )

out = {
    "model": model,
    "claims": exa_claims,
    "proposed_fields": parsed.get("proposed_fields") or [],
    "usage": resp.get("usage"),
    "elapsed_s": resp.get("_elapsed_s"),
    "defects": defects,
}
print("  defects:", json.dumps(defects))
save_raw(label + "_parsed", out)
print(f"lane B ({model}, tier4/llm_synthesis): {len(exa_claims)} claims, "
      f"{len(out['proposed_fields'])} proposed fields")
print("total spend $", total_spend())
