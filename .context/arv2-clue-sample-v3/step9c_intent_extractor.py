"""Step 9c — a THIRD structuring pass: a single-purpose buying-intent quote extractor.

The finding this exists to prove: pass 1 (broad extraction) and pass 2 (a rubric-driven P1 sweep
over the same corpus) BOTH missed the run's single best buying-intent claim — Kate Blumberg's
30 Jul 2026 post comparing Riveter and Clay for ABM list-building — even though pass 2's charter
named "a tool they publicly praised or criticised" as the top-priority target.

So pass 3 does exactly ONE thing: pull every verbatim public statement by the five members that
touches software tooling, martech, GTM capability, sales bottlenecks or team scaling, as
`contact.facet.recent_post` rows. Narrow beats rubric.
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
reports = {v: open(f"person_report_{k}.md").read() for k, v in ENTITIES.items()}

SYSTEM = """You extract VERBATIM public statements from research reports. You do exactly one thing.

TASK: find every statement the SUBJECT THEMSELVES made publicly (a post, an interview quote, a
byline) that touches ANY of:
  - a named software tool, vendor or category they praised, criticised or compared;
  - the state of their martech / GTM / sales stack, or a gap in it;
  - target-account lists, account research, prospecting, outbound, ABM or lead generation;
  - a sales or go-to-market BOTTLENECK they named;
  - a team size they are scaling to, or a hiring mandate they were given or are executing.

For each, emit ONE row:
  {"entity", "field_key": "contact.facet.recent_post", "value_json": "<the verbatim statement>",
   "evidence_span": "<the same verbatim statement, exactly as it appears in the report>",
   "source_url": "<the URL the report attributes it to>", "confidence": <0-1>,
   "priority": 1, "use_class": "professional-public"}

HARD RULES
  * value_json and evidence_span must both be VERBATIM text present in the report. Copy, never
    paraphrase, never re-punctuate.
  * Attribute only statements BY the subject. A statement about them by someone else does not
    qualify — except a direct quotation of the subject inside someone else's post, which does.
  * Skip anything the report marked NOT FOUND. Skip special-category material entirely.
  * If a person has no qualifying statement, emit no row for them. Never emit a placeholder,
    never emit "NOT FOUND" as a value, never emit an empty array.
  * Emit at MOST 4 rows per person, best first.

Return ONLY {"contact_claims": [...]}."""

USER = "\n\n".join(
    f"# ENTITY {ent}\n{txt}" for ent, txt in reports.items()
)

open("structuring_bundle_intent.txt", "w").write(SYSTEM + "\n\n=====\n\n" + USER)

if "--from-cache" in sys.argv:
    resp = json.load(open("raw/structure_intent_extract.json"))
else:
    resp = C.openrouter(
        "openai/gpt-5-mini",
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        label="structure_intent_extract",
        response_format={"type": "json_object"},
        timeout=900,
        reasoning={"effort": "minimal"},
    )
parsed = json.loads(((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
C.save_raw("structure_intent_parsed", parsed)
rows = parsed.get("contact_claims") or []
print(f"intent extractor: {len(rows)} rows")
for r in rows:
    print(f"  {r.get('entity')}: {json.dumps(r.get('value_json'))[:190]}")
    print(f"      {r.get('source_url')}")
print("TOTAL:", C.total_spend())
