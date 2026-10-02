"""Step 7 — THE contact deep call. Exactly ONE Exa `deep-reasoning` request on the primary contact.

Uses the step-3 finding: the synthesis stage only runs when an outputSchema exists, so the schema is
a SINGLE free-form string property (not a rigid field schema).

Compliance rule baked into the charter: professional and non-sensitive personal hooks only. Health,
religion, politics, family tragedy, sexual orientation, ethnicity and union membership are
special-category (Doc D) and are explicitly refused, not merely "avoided".
"""

import json

from clue_lib import exa, exa_output_text, save_raw, total_spend

SYS = """You are researching ONE named person for a respectful, well-informed B2B outreach letter.

THE EXACT PERSON:
  Name: Steijn Pelle
  Role: co-founder and CEO of Lassie (lassie.ai), the San Francisco AI company automating
        dental/medical practice administration; raised a $35M Series A led by a16z, June 2026.
  LinkedIn: linkedin.com/in/steijn        Personal site: steijn.com
  Work email on record: steijn@lassie.ai
  Prior roles on record: Product Manager at Robinhood (2018-2019); Product Lead, Growth at
  Coinbase (2018); Product Manager, Growth at HealthTap (2016-2018); COO & co-founder of FITMO;
  CEO & co-founder of Pelliano; CEO & co-founder of ELF Entertainment.

DISAMBIGUATION: ignore anyone else named Pelle, anything about the Swedish pet-insurance company
Lassie (lassie.co), and anything about the fictional collie. If a source is about a different
person, discard it and say so.

HARD COMPLIANCE RULE - this is not a preference, it is a refusal:
  * ALLOWED: professional history, education, public writing/talks/podcasts, awards, publicly
    stated hobbies and interests, hometown/nationality as publicly self-stated, tenure milestones,
    community and volunteering that is not religious or political, sports teams, languages.
  * FORBIDDEN - do not collect, do not report, even if you find it: health or medical information,
    religion or religious activity, political views or affiliation, sexual orientation, racial or
    ethnic origin, trade-union membership, family bereavement or personal tragedy, anything about
    children or family members, home address, personal phone, personal email.
  If a source contains forbidden material, do not quote it; write "excluded: special-category".

Ground EVERY fact in a public page: give the fact, a VERBATIM QUOTE copied exactly, and the SOURCE
URL. Write "NOT FOUND" rather than guessing. Prefer primary sources (his own LinkedIn posts,
steijn.com, his own interviews, company pages) over aggregators.

Produce a long markdown report with these numbered sections; never skip one.

1. IDENTITY CONFIRMATION - state exactly which sources tie THIS Steijn Pelle to Lassie/lassie.ai
   (self-authored profile, company page, funding release, interview). Quote the tying language and
   give the URL. Then state your confidence that every later section is about the same person, and
   list anything you deliberately excluded as a possible different person.
2. CURRENT ROLE AND TENURE - his exact current title, when he started, how he describes his own
   job in his own words, and what he owns (product? growth? sales?). Quote.
3. CAREER HISTORY - every prior role with company, title, dates and a source; note especially his
   growth/marketing track record (Robinhood referral programme, Coinbase growth, HealthTap growth)
   and his earlier founded companies. Quote each.
4. EDUCATION - schools, degrees, fields, years, with sources. Quote.
5. PUBLIC WRITING, TALKS AND PODCASTS - articles, essays, newsletters, podcast appearances,
   conference talks, LinkedIn posts of substance. For each: title, venue, URL, date, and a
   representative verbatim quote in his own voice.
6. AWARDS AND RECOGNITION - any awards, lists, honours, with sources, or NOT FOUND.
7. HOW HE THINKS AND WRITES - his communication style, recurring themes and opinions, the words he
   reuses. Support each observation with a verbatim quote in his own voice.
8. NON-SENSITIVE PERSONAL HOOKS - publicly stated hometown or country of origin, languages,
   alma mater loyalties, hobbies, sports, side projects, tenure milestones, non-religious and
   non-political community involvement. Each with a verbatim quote and URL. If a category is
   empty write NOT FOUND. Apply the forbidden list above without exception.
9. WHAT HE IS PUBLICLY WORKING ON OR WORRIED ABOUT RIGHT NOW - his most recent public statements
   about hiring, growth, distribution, or the business, newest first, with dates and URLs. Quote.
10. SUGGESTED OPENERS - three to five opening lines for a letter or email. Each opener MUST be
    grounded in a specific hook from sections 5, 7, 8 or 9, and MUST name the exact hook and its
    source URL underneath it. No opener may reference anything not found above. No flattery that
    is not backed by a quote.
11. SOURCE LIST - every URL used, one per line, marked [primary] or [secondary].
"""

QUERY = (
    "Steijn Pelle, co-founder and CEO of Lassie (lassie.ai) in San Francisco: his background at "
    "Robinhood and Coinbase growth, HealthTap, his earlier startups FITMO and Pelliano, his "
    "education, his interviews, podcasts and LinkedIn posts about building Lassie for dental "
    "practices, how he writes and what he says about growth, hiring and distribution"
)

resp = exa(
    {
        "query": QUERY,
        "type": "deep-reasoning",
        "numResults": 25,
        "systemPrompt": SYS,
        "outputSchema": {
            "type": "object",
            "description": (
                "One long markdown report. Put the ENTIRE 11-section profile, with every verbatim "
                "quote and source URL inline, into the single 'report' string. Do not summarise."
            ),
            "properties": {
                "report": {
                    "type": "string",
                    "description": (
                        "The complete 11-section markdown profile described in the system prompt, "
                        "with verbatim quotes and source URLs inline for every fact."
                    ),
                }
            },
            "required": ["report"],
        },
        "contents": {
            "text": {"maxCharacters": 10000},
            "highlights": {
                "query": "Steijn Pelle Lassie CEO background growth Robinhood education interests",
                "maxCharacters": 2000,
            },
        },
        "stream": False,
    },
    label="contact_deep_steijn",
    timeout=900,
)

raw_out = resp.get("output")
report = ""
if isinstance(raw_out, dict):
    content = raw_out.get("content")
    if isinstance(content, dict):
        report = content.get("report") or json.dumps(content, indent=2)
    elif isinstance(content, str):
        try:
            report = json.loads(content).get("report") or content
        except Exception:
            report = content
if not report:
    report = exa_output_text(resp)

save_raw("contact_deep_report_text", {"chars": len(report), "report": report})
open("contact_report.md", "w").write(report)
print("\n---- report chars:", len(report))
print("cost:", (resp.get("costDollars") or {}).get("total"), "total spend $", total_spend())
print(report[:2000])
