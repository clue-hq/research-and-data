"""Step 8 — one Exa `deep-reasoning` call PER confirmed committee member (founder ruling #2).

Five subjects, five calls, per-person cost recorded. Each call is target-locked in the
systemPrompt with the exact person, exact current employer AND their Apollo-confirmed prior
employers, because three of the five names ("Mark Hoffman", "Kate Blumberg", "Aaron Churba") are
common enough to collide. Compliance charter excludes special-category data by construction.
"""

import json
import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

committee = json.load(open("committee.json"))

PRIORS = {
    "eliadis": "Probook (co-founder & CEO, since 2021), A2Z Exterior Pressure Washing (contractor), "
    "Eliadis Numismatics; University of Pennsylvania M&T dual-degree programme",
    "hoffman": "Probook (CRO, since Feb 2026), Tennr (Chief Sales Officer, Dec 2024–Feb 2026), "
    "VTS (SVP/VP/Director of Sales, 2017–2024), Hightower Inc., Zocdoc (2013–2016)",
    "blumberg": "Probook (Director of Growth, since Jun 2026), BuildOps (Director of Demand "
    "Generation, 2024–2026), Middesk (Head of Growth), SafeGraph (Director of Demand Generation), "
    "Survata (Head of Demand Generation), Branch (ABM Manager / Global Events Manager / SDR team "
    "lead). Her LinkedIn handle is 'kibrady12', so she may also appear under a previous surname.",
    "churba": "Probook (Director of Sales & Development, since Feb 2026), Bite (Director of Sales / "
    "Advisor), Zip Security (Director of Sales), Electric (Manager, Sales / Senior AE)",
    "zhang": "Probook (co-founder & CTO, since 2024), Roblox (Senior ML Engineer, 2021–2024), "
    "internships at Confluent, Rubrik, Tesla and Intel; UC Berkeley EECS; Berkeley AI Research and "
    "Stanford research internships",
}

SYSTEM_TMPL = """You are researching ONE named professional for a B2B buying-committee dossier.

TARGET LOCK — the ONLY subject is:
  {name}, currently {title} at Probook (probook.ai), the AI operating system for home-services
  businesses (plumbing / HVAC / electrical), headquartered in New York, NY.
  LinkedIn: {linkedin}
  Known employment history (already verified, use it to disambiguate): {priors}

Any person with the same or a similar name who does NOT match that employment history is a
DIFFERENT PERSON. Name every same-name person you encountered and discarded, and say why.

COMPLIANCE CHARTER — hard exclusions. Do NOT collect, report, quote or allude to: health or
medical information, religion or religious activity, political opinions or affiliation, sexual
orientation, racial or ethnic origin, trade-union membership, criminal matters, family or
bereavement details, home address, personal phone number or personal email address, or anything
about their children. If a source contains such material, skip it and say you skipped it. Only
professionally-public and clearly non-sensitive personal material is in scope.

RULES: every assertion carries a verbatim quote and its URL. Write "NOT FOUND" rather than
guessing. Prefer the person's own words (their posts, talks, interviews, bylines) over third-party
profiles. Aggregator/people-directory pages are the weakest evidence and must be labelled as such.
"""

CHARTER_TMPL = """Produce an exhaustive, cited markdown profile of {name} ({title} at Probook):

1. IDENTITY CONFIRMATION — the primary sources that tie this exact person to Probook and this
   exact title, with dates. List the same-name people you excluded.
2. CAREER — every role with organisation, title and start/end dates, and what they were
   responsible for at each. Highlight anything to do with outbound sales, demand generation,
   account-based marketing, target-account list building, sales development or GTM tooling.
3. EDUCATION — institutions, degrees, dates, and any post-graduate or professional programmes.
4. PUBLIC WRITING, TALKS AND PODCASTS — every post, article, byline, webinar, panel or podcast
   appearance you can find, with title, venue, date and URL. Quote the most substantive one.
5. WHAT THEY OWN AT PROBOOK TODAY — scope of the role, who reports to them, which open Probook
   roles report into them, and what they have publicly said about what they are building.
6. HOW THEY THINK AND BUY — evidence about how they evaluate and purchase software: tools they
   have publicly praised or criticised, methodologies they advocate, their stated metrics, and
   their communication style (quote them).
7. NON-SENSITIVE PERSONAL HOOKS — publicly stated interests, hobbies, sports, schools, awards,
   volunteering, side projects. Nothing from the compliance exclusion list.
8. THREE GROUNDED CONVERSATION OPENERS — each must name the exact hook it uses and the URL that
   evidences it. No opener may rest on an unsourced fact.
"""

results = []
for m in committee:
    label = f"person_deep_{m['key']}"
    resp = C.exa(
        {
            "query": CHARTER_TMPL.format(name=m["name"], title=m["apollo_title"]),
            "type": "deep-reasoning",
            "systemPrompt": SYSTEM_TMPL.format(
                name=m["name"],
                title=m["apollo_title"],
                linkedin=m["web_linkedin_url"],
                priors=PRIORS[m["key"]],
            ),
            "outputSchema": {
                "type": "object",
                "required": ["report"],
                "additionalProperties": False,
                "properties": {
                    "report": {
                        "type": "string",
                        "description": "The exhaustive cited markdown profile answering every "
                        "numbered section, with a verbatim quote and URL behind every assertion "
                        "and explicit NOT FOUND markers.",
                    }
                },
            },
        },
        label=label,
        timeout=900,
    )
    text = C.exa_output_text(resp)
    if text.strip().startswith("{"):
        try:
            obj = json.loads(text)
            r = obj.get("report")
            text = r.get("value") if isinstance(r, dict) else (r or text)
        except Exception:
            pass
    path = f"person_report_{m['key']}.md"
    open(path, "w").write(text)
    cost = (resp.get("costDollars") or {}).get("total")
    results.append({"key": m["key"], "name": m["name"], "chars": len(text), "cost_usd": cost})
    print(f"  {m['name']}: {len(text)} chars, NOT FOUND x{text.count('NOT FOUND')}, ${cost}")

json.dump(results, open("person_deep_costs.json", "w"), indent=2)
print("\nper-person deep total:", round(sum(r["cost_usd"] or 0 for r in results), 4))
print("TOTAL:", C.total_spend())
