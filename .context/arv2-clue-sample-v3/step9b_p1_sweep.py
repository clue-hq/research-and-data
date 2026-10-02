"""Step 9b — a SECOND structuring pass: the priority-1 sweep.

Why it exists (measured, not assumed): pass 1 (`step9_structure.py`) emitted 32 tier-4 claims and
100%-valid schemas, but it under-harvested the run's strongest buying-intent evidence — Kate
Blumberg's public martech evaluation, George Eliadis's "founder-led sales isn't a flex", Aaron
Churba's "5 sellers and counting" — and it left five REGISTERED facet fields
(`communication_style`, `stated_interests`, `recent_award`, `conference_talk`,
`public_appearances`) completely empty even though the reports evidence them.

So pass 2 is a narrow, rubric-driven sweep over the SAME corpus with an explicit P1 charter and an
explicit list of the registered fields still unused. Same model, same price class. Both passes are
reported separately; the merge dedupes.
"""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402
from field_catalog import catalog_text  # noqa: E402

ENTITIES = {
    "eliadis": "contact:george-eliadis",
    "hoffman": "contact:mark-hoffman",
    "blumberg": "contact:kate-blumberg",
    "churba": "contact:aaron-churba",
    "zhang": "contact:lewis-zhang",
}
account_report = open("account_report.md").read()
person_reports = {k: open(f"person_report_{k}.md").read() for k in ENTITIES}

SYSTEM = """You are running a SECOND, NARROW extraction pass over research reports that have already
been mined once. Your job is to harvest the evidence the first pass MISSED.

ABSOLUTE RULES (unchanged): catalog field_keys only; value_json must validate against the field's
value_schema; evidence_span must be a VERBATIM substring of the material; every row needs the
source_url the report attributes the fact to; never emit anything marked "NOT FOUND"; never emit
special-category material (health, religion INCLUDING a religion field-of-study, politics, sexual
orientation, ethnicity, union membership, criminal matters, family/bereavement, home address,
personal phone/email). Do not emit provenance fields — the caller stamps those.

WHAT THIS PASS IS FOR — in priority order:
  A. PRIORITY-1 BUYING-INTENT EVIDENCE. Any statement by a person that shows they are actively
     evaluating, buying, building or bottlenecked on go-to-market capability: a tool they publicly
     praised or criticised, a category they said is noisy or crowded, a hiring plan, a team size
     they are scaling to, a bottleneck they named, a growth mandate they were given. These are the
     single most valuable rows in the run. Use `contact.facet.recent_post` for a verbatim public
     statement; ONE ROW PER DISTINCT STATEMENT (the field may repeat across rows).
  B. REGISTERED FIELDS THE FIRST PASS LEFT EMPTY, listed in the user message. Fill each one that
     the reports genuinely evidence, and leave the rest empty.

Emit `priority` on every row: 1 for active buying intent / a dated timing statement, 2 for
qualifying professional facts, 3 for background and personal colour.

Return ONLY {"contact_claims":[...], "account_claims":[...], "proposed_fields":[...]}.
Each contact claim: {"entity","field_key","value_json","evidence_span","source_url","confidence",
"priority","use_class"(for contact.facet.*)}.
Each proposed field: {"field_key","entity_type","value_type","value_schema","description",
"reuse_scope","hypothesis","example_value","example_evidence_span","example_source_url","priority"}
— propose a field ONLY when a genuinely high-value fact has no honest home in the catalog."""

USER = f"""# FIELD CATALOG (the ONLY keys you may use)
{catalog_text()}

# ENTITY IDS
  contact:george-eliadis  — George Eliadis, Co-Founder & CEO, Probook
  contact:mark-hoffman    — Mark Hoffman, Chief Revenue Officer, Probook
  contact:kate-blumberg   — Kate Blumberg, Director of Growth, Probook
  contact:aaron-churba    — Aaron Churba, Director of Sales & Development, Probook
  contact:lewis-zhang     — Lewis Zhang, Co-Founder & CTO, Probook
  account:probook         — Probook (probook.ai)

# THE CLIENT DOING THE SELLING
Clue — an AI-native ABM orchestration platform: it discovers target accounts, researches accounts
and their buying committees to dossier depth, and drafts personalised campaign content. Judge
"buying intent" against THAT sale: anything about target-account lists, account research, outbound,
ABM, prospect data quality, martech evaluation or GTM headcount is priority 1.

# REGISTERED FIELDS PASS 1 LEFT COMPLETELY EMPTY — fill the ones the reports evidence
  contact.facet.communication_style   (every report has a "communication style" paragraph)
  contact.facet.stated_interests
  contact.facet.recent_award
  contact.facet.conference_talk
  contact.facet.public_appearances
  contact.facet.hobby
  contact.facet.nickname
  account.operational_pain
  account.resonance.buying_culture

# THE REPORTS
## account:probook
{account_report}

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

Harvest now. Priority-1 buying-intent statements first."""

open("structuring_bundle_p1sweep.txt", "w").write(SYSTEM + "\n\n=====\n\n" + USER)

if "--from-cache" in sys.argv:
    resp = json.load(open("raw/structure_p1_sweep.json"))
else:
    resp = C.openrouter(
        "openai/gpt-5-mini",
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        label="structure_p1_sweep",
        response_format={"type": "json_object"},
        timeout=900,
        reasoning={"effort": "minimal"},
    )
txt = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
parsed = json.loads(txt)
C.save_raw("structure_p1_sweep_parsed", parsed)
print(
    f"sweep: {len(parsed.get('contact_claims') or [])} contact claims, "
    f"{len(parsed.get('account_claims') or [])} account claims, "
    f"{len(parsed.get('proposed_fields') or [])} proposed fields"
)
for r in (parsed.get("contact_claims") or []) + (parsed.get("account_claims") or []):
    print(f"  P{r.get('priority')} {r.get('entity','account:probook')} {r.get('field_key')}")
    print("      ", json.dumps(r.get("value_json"))[:180])
print("TOTAL:", C.total_spend())
