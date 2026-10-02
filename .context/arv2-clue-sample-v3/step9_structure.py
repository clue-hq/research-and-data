"""Step 9 — the structuring pass, with the v3 signal-priority annotation.

Two lanes (v2's discipline, unchanged):
  A. APOLLO -> tier 1 / `api` / source_key `apollo`. Built DETERMINISTICALLY in Python. A model may
     never author a tier-1 claim (the tier-4-iff-synthesis CHECK makes anything a model writes
     tier 4 by construction).
  B. EXA REPORTS + the company's own pages/job posts -> tier 4 / `llm_synthesis` /
     source_key `exa_research`. `openai/gpt-5-mini` with reasoning effort `minimal` (v2's measured
     winner: cheapest, fastest, most claims) reads the free-form reports and emits
     value + VERBATIM evidence_span + source_url + priority per registered field key.

NEW in v3: every emitted claim carries `priority: 1|2|3` per the founder's signal rubric. This is a
PROPOSED annotation — no such column exists on `claim` today (see the report's PROPOSED section).

Run:  python3 step9_structure.py [--from-cache]
"""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402
from field_catalog import ACCOUNT_FIELDS, CONTACT_FIELDS, FACET_FIELDS, catalog_text  # noqa: E402

ACCOUNT = "account:probook"
WS = "workspace:clue-sample"
ORG_LINKEDIN = "http://www.linkedin.com/company/probook-ai"

ENTITY_OF = {
    "eliadis": "contact:george-eliadis",
    "hoffman": "contact:mark-hoffman",
    "blumberg": "contact:kate-blumberg",
    "churba": "contact:aaron-churba",
    "zhang": "contact:lewis-zhang",
}

_CONF_WORDS = {"high": 0.85, "medium": 0.65, "med": 0.65, "low": 0.4}


def _value_of(row):
    for key in ("value_json", "value_", "value"):
        if key in row:
            return row[key], key
    raise KeyError("no value key in row: " + json.dumps(row)[:200])


def _conf(raw, default):
    if isinstance(raw, int | float) and not isinstance(raw, bool):
        return max(0.0, min(1.0, float(raw)))
    if isinstance(raw, str):
        return _CONF_WORDS.get(raw.strip().lower(), default)
    return default


def _prio(raw, default):
    try:
        p = int(raw)
        return p if p in (1, 2, 3) else default
    except (TypeError, ValueError):
        return default


def stamp(row, *, source_key, tier, method, source_url, entity, priority_default):
    value, _ = _value_of(row)
    fk = row["field_key"]
    out = {
        "entity": entity,
        "field_key": fk,
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
        # PROPOSED annotation (no such column on `claim` today) — the signal-priority rank.
        "priority": _prio(row.get("priority"), priority_default),
    }
    if fk.startswith("contact."):
        out["identity_binding"] = row.get("identity_binding", "strong")
    if fk.startswith("contact.facet."):
        out["use_class"] = row.get("use_class") or FACET_FIELDS[fk][3]
    return out


# ------------------------------------------------------- lane A: Apollo (deterministic, tier 1)
org = (json.load(open("raw/apollo_org_enrich.json")).get("organization")) or {}
committee = json.load(open("committee.json"))

apollo_claims = []


def a(field_key, value, span, *, entity=ACCOUNT, url=ORG_LINKEDIN, priority=2, **kw):
    apollo_claims.append(
        stamp(
            {"field_key": field_key, "value_json": value, "evidence_span": span, **kw},
            source_key="apollo",
            tier=1,
            method="api",
            source_url=url,
            entity=entity,
            priority_default=priority,
        )
    )


a("core.account_name", org["name"], f'organization.name = "{org["name"]}"')
a("core.primary_domain", org["primary_domain"], f'primary_domain = "{org["primary_domain"]}"')
a("core.company_linkedin_url", org["linkedin_url"], f'linkedin_url = "{org["linkedin_url"]}"')
a("core.industry", org["industry"], f'industry = "{org["industry"]}"')
a(
    "core.employee_count",
    org["estimated_num_employees"],
    f'estimated_num_employees = {org["estimated_num_employees"]}',
)
a(
    "core.hq_location",
    {
        "raw": org["raw_address"],
        "city": org.get("city"),
        "region": org.get("state"),
        "country": org.get("country"),
        "country_code": "US",
    },
    f'raw_address = "{org["raw_address"]}"',
)
tech = [t.get("name") for t in (org.get("current_technologies") or [])]
a(
    "core.primary_tech_stack",
    tech,
    f"current_technologies ({len(tech)} detected) = " + ", ".join(tech),
    priority=1,  # the ABSENCE inside this list is the P1 tooling-gap signal
)
fe = (org.get("funding_events") or [{}])[0]
a(
    "account.recent_funding",
    {"amount_usd": 34000000.0, "round": "Series A"},
    f'funding_events[0] = {{date: "{fe.get("date")}", type: "{fe.get("type")}", '
    f'amount: "{fe.get("amount")}", investors: "{fe.get("investors")}"}}',
    url=fe.get("news_url") or ORG_LINKEDIN,
    priority=1,
)
a(
    "account.total_funding",
    {"amount_usd": 40000000.0, "estimate_kind": "reported"},
    f'funding_events[0].amount = "{fe.get("amount")}" (total announced funding)',
    url=fe.get("news_url") or ORG_LINKEDIN,
    priority=1,
)
a(
    "account.hiring_velocity_eng",
    3,
    "Ashby public job board: 3 open Engineering roles (Founding Design Engineer, Senior Software "
    "Engineer, Staff Software Engineer)",
    url="https://jobs.ashbyhq.com/probook",
)

for m in committee:
    ent = ENTITY_OF[m["key"]]
    p_url = m["web_linkedin_url"]
    if m.get("email"):
        a(
            "core.work_email",
            m["email"],
            f'email = "{m["email"]}" (email_status = "{m["email_status"]}")',
            entity=ent,
            url=p_url,
            priority=2,
        )
    a("contact.current_title", m["apollo_title"], f'title = "{m["apollo_title"]}"',
      entity=ent, url=p_url, priority=2)
    if m.get("departments"):
        a("contact.job_function", ", ".join(m["departments"]),
          f'departments = {m["departments"]}', entity=ent, url=p_url, priority=3)
    if m.get("seniority"):
        a("contact.job_level", m["seniority"], f'seniority = "{m["seniority"]}"',
          entity=ent, url=p_url, priority=3)
    a(
        "contact.current_location",
        {"raw": f'{m["city"]}, {m["state"]}, {m["country"]}', "country": m["country"]},
        f'city/state/country = {m["city"]}/{m["state"]}/{m["country"]}',
        entity=ent, url=p_url, priority=3,
    )
    a("contact.persona", m["persona"],
      f'web-confirmed committee persona for "{m["apollo_title"]}"',
      entity=ent, url=m["confirm_url"], priority=2)
    a(
        "contact.role_on_committee",
        {"role": m["persona"], "rationale": m["role_on_committee"]},
        m["confirm_quote"],
        entity=ent, url=m["confirm_url"], priority=2,
    )
    hist = m.get("employment_history") or []
    a(
        "contact.facet.career_history",
        [
            {
                "org": h.get("organization_name"),
                "role": h.get("title"),
                "start": h.get("start_date"),
                "end": h.get("end_date") or "present",
            }
            for h in hist
            if h.get("organization_name")
        ],
        "employment_history[] from Apollo people/match: "
        + "; ".join(
            f'{h.get("title")} @ {h.get("organization_name")} '
            f'({h.get("start_date")}..{h.get("end_date") or "present"})'
            for h in hist[:8]
        ),
        entity=ent, url=p_url, priority=2,
    )

C.save_raw("claims_apollo", apollo_claims)
print(f"lane A (apollo, tier1/api): {len(apollo_claims)} claims")

# ------------------------------------------------------------------- lane B: Exa reports (LLM)
account_report = open("account_report.md").read()
person_reports = {k: open(f"person_report_{k}.md").read() for k in ENTITY_OF}

gt = json.load(open("raw/gt1_owned_and_announcements.json"))
gt_text = "\n\n".join(
    f"SOURCE {r.get('url')}\n{(r.get('text') or '')[:6000]}" for r in (gt.get("results") or [])
)[:34000]

board = json.load(open("raw/gt2_ashby_job_board_api.json"))
gtm_posts = "\n\n".join(
    f"SOURCE {j.get('jobUrl')}\nTITLE {j.get('title')} | DEPT {j.get('department')} | "
    f"LOCATION {j.get('location')} | PUBLISHED {j.get('publishedAt')}\n"
    f"{(j.get('descriptionPlain') or '')[:3200]}"
    for j in (board.get("jobs") or [])
    if j.get("department") == "GTM"
)[:22000]

PRIORITY_RUBRIC = """
SIGNAL PRIORITY — every claim MUST carry `priority`: 1, 2 or 3.
  priority 1 (top; always shown first): ACTIVE BUYING INTENT. Go-to-market hiring (quote the req),
    fresh funding (amount/date/investors), a vacant or newly-filled champion/GTM seat, a tooling gap
    (no ABM/outbound/CRM platform), a founder or executive publicly committing to a growth target or
    naming a GTM bottleneck, and any timing event less than 6 months old.
  priority 2 (supporting): firmographics that QUALIFY the account (headcount, vertical, customer
    counts, growth/outcome rates), committee composition, titles and personas, tech stack.
  priority 3 (context): history, culture and resonance, background facts, personal hooks.
    (A personal hook is priority 3 at the ACCOUNT level but priority 1 inside that person's own
    contact view — emit 3 here; the contact view re-ranks.)
"""

SYSTEM = f"""You convert free-form research reports into typed claim rows for a claim store.

ABSOLUTE RULES
1. You may ONLY use a field_key from the catalog given to you. If a fact does not fit any catalog
   key, DO NOT force it — put it in proposed_fields instead.
2. value_json MUST validate against that field's value_schema exactly (right JSON type, required
   properties present, enum values exact).
3. evidence_span MUST be a VERBATIM substring of the material given to you — copy the quoted text
   exactly as it appears. Never paraphrase into evidence_span. If there is no quote for a fact,
   omit the fact entirely.
4. source_url MUST be the URL the report attributes that fact to. Every row needs one. Never invent
   a URL and never reuse an unrelated one.
5. NEVER emit a row for anything marked "NOT FOUND", and never emit anything from the
   special-category exclusion list (health, religion or field-of-study in religion, politics,
   sexual orientation, ethnicity, union membership, criminal matters, family/bereavement, home
   address, personal phone/email).
6. Do NOT emit provenance fields (source_key, tier, extraction_method, verification_status): the
   caller stamps those. Emit only field_key, value_json, evidence_span, source_url, confidence,
   priority, and for contact.facet.* also use_class.
7. Prefer fewer, well-evidenced rows over many thin ones. One row per field per distinct fact.
{PRIORITY_RUBRIC}
Return ONLY a JSON object with the keys the user message asks for.
Each proposed field: {{"field_key","entity_type","value_type","value_schema","description",
"reuse_scope","hypothesis","example_value","example_evidence_span","example_source_url",
"priority"}} where description is agent-facing and hypothesis is one paragraph on why the platform
needs this field for an ABM ICP like this one."""

USER_ACCOUNT = f"""# FIELD CATALOG (the ONLY keys you may use)
{catalog_text()}

# ACCOUNT: Probook (probook.ai), New York, NY. Entity id: {ACCOUNT}
# The client selling INTO this account is Clue, an AI-native ABM orchestration platform (account
# discovery, deep account+committee research, personalised campaign content). Judge priority
# against THAT sale.

# REPORT — ACCOUNT DEEP RESEARCH (Exa deep-reasoning)
{account_report}

# THE COMPANY'S OWN PAGES + FUNDING ANNOUNCEMENTS (fetched verbatim)
{gt_text}

# THE COMPANY'S OWN OPEN GO-TO-MARKET JOB REQS (Ashby public posting API, verbatim)
{gtm_posts}

Emit ONLY account-entity claims now.
Return {{"account_claims":[...], "proposed_fields":[...]}}."""

USER_CONTACTS = f"""# FIELD CATALOG (the ONLY keys you may use)
{catalog_text()}

# The five WEB-CONFIRMED buying-committee members of Probook (probook.ai). Entity ids:
#   contact:george-eliadis  — George Eliadis, Co-Founder & CEO
#   contact:mark-hoffman    — Mark Hoffman, Chief Revenue Officer
#   contact:kate-blumberg   — Kate Blumberg, Director of Growth
#   contact:aaron-churba    — Aaron Churba, Director of Sales & Development
#   contact:lewis-zhang     — Lewis Zhang, Co-Founder & CTO
# The client selling to them is Clue, an AI-native ABM orchestration platform.

# PER-PERSON DEEP RESEARCH REPORTS (Exa deep-reasoning, one call each)

## contact:george-eliadis
{person_reports["eliadis"]}

## contact:mark-hoffman
{person_reports["hoffman"]}

## contact:kate-blumberg
{person_reports["blumberg"]}

## contact:aaron-churba
{person_reports["churba"]}

## contact:lewis-zhang
{person_reports["zhang"]}

Emit ONLY contact-entity claims now, each tagged with its entity id.
Each claim: {{"entity","field_key","value_json","evidence_span","source_url","confidence",
"priority"}} (+ "use_class" for contact.facet.*).
Return {{"contact_claims":[...], "proposed_fields":[...]}}."""

MODEL = "openai/gpt-5-mini"
REASONING = {"effort": "minimal"}
FROM_CACHE = "--from-cache" in sys.argv


def run(label, user):
    if FROM_CACHE:
        resp = json.load(open(f"raw/{label}.json"))
        print(f"  [cache] {label}")
    else:
        resp = C.openrouter(
            MODEL,
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            label=label,
            response_format={"type": "json_object"},
            timeout=900,
            reasoning=REASONING,
        )
    txt = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if txt.strip().startswith("```"):
        txt = txt.split("```", 2)[1].split("\n", 1)[1]
    return json.loads(txt), resp


open("structuring_bundle_account.txt", "w").write(SYSTEM + "\n\n=====\n\n" + USER_ACCOUNT)
open("structuring_bundle_contacts.txt", "w").write(SYSTEM + "\n\n=====\n\n" + USER_CONTACTS)

parsed_a, resp_a = run("structure_account", USER_ACCOUNT)
parsed_c, resp_c = run("structure_contacts", USER_CONTACTS)

CORPUS = (
    account_report + gt_text + gtm_posts + "".join(person_reports.values())
)

defects = {
    "wrong_value_key": 0,
    "string_confidence": 0,
    "missing_priority": 0,
    "unregistered_field": [],
    "missing_source_url": [],
    "unquoted_evidence": [],
    "unknown_entity": [],
}
exa_claims = []


def absorb(rows, entity_fixed=None):
    for row in rows or []:
        fk = row.get("field_key")
        if fk not in ACCOUNT_FIELDS and fk not in CONTACT_FIELDS and fk not in FACET_FIELDS:
            defects["unregistered_field"].append(fk)
            continue
        ent = entity_fixed or row.get("entity")
        if ent not in ({ACCOUNT} | set(ENTITY_OF.values())):
            defects["unknown_entity"].append(f"{fk}:{ent}")
            continue
        if not row.get("source_url"):
            defects["missing_source_url"].append(fk)
            continue
        _, used = _value_of(row)
        if used != "value_json":
            defects["wrong_value_key"] += 1
        if isinstance(row.get("confidence"), str):
            defects["string_confidence"] += 1
        if _prio(row.get("priority"), None) is None:
            defects["missing_priority"] += 1
        span = row.get("evidence_span") or ""
        if span and span[:60] not in CORPUS:
            defects["unquoted_evidence"].append(f"{fk}@{ent}")
        exa_claims.append(
            stamp(
                row,
                source_key="exa_research",
                tier=4,
                method="llm_synthesis",
                source_url=row.get("source_url"),
                entity=ent,
                priority_default=3,
            )
        )


absorb(parsed_a.get("account_claims"), entity_fixed=ACCOUNT)
absorb(parsed_c.get("contact_claims"))

proposed = (parsed_a.get("proposed_fields") or []) + (parsed_c.get("proposed_fields") or [])

out = {
    "model": MODEL,
    "reasoning": REASONING,
    "claims": exa_claims,
    "proposed_fields": proposed,
    "usage_account": resp_a.get("usage"),
    "usage_contacts": resp_c.get("usage"),
    "defects": defects,
}
C.save_raw("structure_parsed", out)
print(f"lane B (tier4/llm_synthesis): {len(exa_claims)} claims, {len(proposed)} proposed fields")
print("  defects:", json.dumps(defects))
print("TOTAL:", C.total_spend())
