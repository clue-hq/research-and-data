"""Phase 4b — the UNIQUE-INSIGHT repair pass.

Phase 4 returned "NOT FOUND - thin public footprint" for 7/10 people while their own dossiers
plainly contained distinctive, quote-backed facts (a published cocktail book; a college golf
roster bio; Thai boxing). That was a model conservatism failure, not a data failure — so this
pass asks ONE narrow question per person, forced to quote, with "NOT FOUND" still permitted.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import p_lib as C  # noqa: E402
from roster import PEOPLE  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "openai/gpt-5-mini"

SYS = """You find THE ONE most distinctive, quote-backed fact about a named person — the thing a
generic enrichment tool (Apollo, ZoomInfo, Clay, Clearbit) would NEVER surface, because it is not
on a job record.

RULES
- It must be about THIS person, quote-backed, and URL-backed. Copy the INNERMOST verbatim quote
  (the subject's or source's actual words), never narration about them.
- Rank by distinctiveness: a published book, a competition win, a college-team roster bio, a
  named side project or newsletter, a stated sport or instrument, an unusual career pivot — all
  beat "leads demand generation".
- A company-strategy opinion is NOT a unique insight about the PERSON. Reject it.
- SENSITIVITY FLOOR (hard): nothing about health, faith, politics, sexuality, gender identity,
  family tragedy, minors, unions, or legal matters. Nothing built on national origin or a
  migration story (mark such material outreach_safe=false and do not choose it as the insight).
- If there is genuinely nothing beyond a standard job profile, answer NOT FOUND. Do not stretch.
Return STRICT JSON only."""

USER = """PERSON: {name}, {title} at {company}.

Return exactly:
{{
  "unique_insight": {{
     "text": "<2-4 sentences on the ONE most distinctive fact, or 'NOT FOUND — thin public footprint'>",
     "evidence_quote": "<verbatim, innermost quote>",
     "source_url": "<url>",
     "why_generic_tools_miss_it": "<one sentence>",
     "outreach_safe": true
  }},
  "extra_life_claims": [
     {{"field_key": "contact.facet.hobby|contact.facet.publications|contact.facet.causes|contact.facet.stated_interests|contact.facet.recent_award|contact.facet.conference_talk|contact.facet.public_appearances|contact.facet.nickname",
       "value": <string or array>,
       "evidence_quote": "<verbatim innermost quote>",
       "source_url": "<url>",
       "charter_category": "background|life_outside_work|voice|professional_identity",
       "priority": "P1|P2|P3",
       "use_class": "professional-public|personal-public-non-sensitive",
       "outreach_safe": true}}
  ]
}}

`extra_life_claims` = quote-backed BACKGROUND and LIFE-OUTSIDE-WORK facts present in the dossier
below that are NOT already in the existing claims listed. Empty array is a valid answer.

=== EXISTING CLAIMS ALREADY CAPTURED (do not repeat these) ===
{existing}

=== FULL PERSONAL DOSSIER ===
{dossier}
"""


def main():
    only = sys.argv[1:] or [p["key"] for p in PEOPLE]
    path = os.path.join(HERE, "claims_people.json")
    data = json.load(open(path))
    t0 = time.time()
    for p in PEOPLE:
        if p["key"] not in only:
            continue
        rec = data["people"].get(p["key"])
        if not rec:
            continue
        dossier = open(os.path.join(HERE, f"person_{p['key']}.md")).read()
        existing = "\n".join(f"- {c['field_key']}: {json.dumps(c['value'])[:150]}"
                             for c in rec["claims"])
        user = USER.format(name=p["name"], title=p["title"], company=p["company"],
                           existing=existing, dossier=dossier[:40000])
        resp = C.openrouter(MODEL, [{"role": "system", "content": SYS},
                                    {"role": "user", "content": user}],
                            label=f"p4b_unique_{p['key']}", response_format={"type": "json_object"},
                            timeout=600, reasoning={"effort": "minimal"})
        txt = (((resp.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        try:
            obj = json.loads(txt)
        except Exception:
            m = re.search(r"\{.*\}", txt, re.S)
            obj = json.loads(m.group(0)) if m else {}
        ui = obj.get("unique_insight") or {}
        if ui.get("text"):
            rec["unique_insight"] = ui
        added = 0
        seen_q = {(c.get("evidence_quote") or "")[:60] for c in rec["claims"]}
        for c in (obj.get("extra_life_claims") or []):
            if not c.get("evidence_quote") or not c.get("source_url"):
                continue
            if c["evidence_quote"][:60] in seen_q:
                continue
            c.update({"person_key": p["key"], "person_name": p["name"], "company": p["company"],
                      "identity_binding": "STRONG", "source_timestamp": None,
                      "source_type": c.get("source_type", "other"),
                      "note": "added by the phase-4b unique-insight repair pass"})
            c.setdefault("outreach_safe", True)
            rec["claims"].append(c)
            seen_q.add(c["evidence_quote"][:60])
            added += 1
        import p4_structure as P4
        rec["n_claims"] = len(rec["claims"])
        rec["n_p1"] = sum(1 for c in rec["claims"] if c.get("priority") == "P1")
        rec["depth_score"], rec["depth_detail"] = P4.depth_score(rec["claims"], rec["unique_insight"])
        print(f"  {p['key']:<20} +{added} claims  depth={rec['depth_score']}  "
              f"UI={'NOT FOUND' if str(ui.get('text','')).upper().startswith('NOT FOUND') else 'yes'}")
        json.dump(data, open(path, "w"), indent=2)
    C.timing_record("P4b_unique_repair", time.time() - t0, f"{len(only)} gpt-5-mini narrow calls")
    print(f"\nPhase 4b spend=${C.total_spend()}")


if __name__ == "__main__":
    main()
